#!/usr/bin/env python3
# database_manager_linux.py

import mysql.connector
import logging
import os
from datetime import datetime
from typing import Dict, List, Tuple, Any, Optional
from mysql.connector import Error

def setup_database_logging():
    """Setup logging configuration for database operations"""
    log_dir = os.path.expanduser("~/scripts/logs")
    os.makedirs(log_dir, mode=0o755, exist_ok=True)
    
    log_file = os.path.join(log_dir, f"database_{datetime.now().strftime('%Y%m%d')}.log")
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - [DB] %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )

class DatabaseManager:
    """Database manager class for handling MySQL connections and queries."""
    
    def __init__(self, connection: mysql.connector.MySQLConnection):
        self.connection = connection
        self.logger = logging.getLogger(__name__)
    
    def execute_query(self, query: str, params: Tuple = None) -> Optional[List[Dict]]:
        """Execute a query and return results."""
        cursor = None
        try:
            cursor = self.connection.cursor(dictionary=True, buffered=True)
            
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            
            # Check if it's a SELECT query
            if query.strip().upper().startswith('SELECT'):
                results = cursor.fetchall()
                self.logger.debug(f"Query returned {len(results)} rows")
                return results
            else:
                # For INSERT, UPDATE, DELETE queries
                self.connection.commit()
                affected_rows = cursor.rowcount
                self.logger.debug(f"Query affected {affected_rows} rows")
                return [{'affected_rows': affected_rows}]
                
        except Error as e:
            self.logger.error(f"Database query error: {e}")
            self.logger.error(f"Query: {query[:200]}...")  # Log first 200 chars of query
            if self.connection.is_connected():
                self.connection.rollback()
            return None
        except Exception as e:
            self.logger.error(f"Unexpected database error: {e}")
            return None
        finally:
            if cursor:
                cursor.close()
    
    def execute_many(self, query: str, params_list: List[Tuple]) -> bool:
        """Execute a query multiple times with different parameters."""
        cursor = None
        try:
            cursor = self.connection.cursor()
            cursor.executemany(query, params_list)
            self.connection.commit()
            self.logger.info(f"Batch operation completed: {cursor.rowcount} rows affected")
            return True
        except Error as e:
            self.logger.error(f"Database batch operation error: {e}")
            if self.connection.is_connected():
                self.connection.rollback()
            return False
        finally:
            if cursor:
                cursor.close()
    
    def is_connected(self) -> bool:
        """Check if database connection is still active."""
        try:
            return self.connection.is_connected()
        except:
            return False
    
    def ping_connection(self) -> bool:
        """Ping the database to keep connection alive."""
        try:
            self.connection.ping(reconnect=True)
            return True
        except Error as e:
            self.logger.error(f"Database ping failed: {e}")
            return False
    
    def get_connection_info(self) -> Dict[str, Any]:
        """Get connection information."""
        try:
            return {
                'server_info': self.connection.get_server_info(),
                'connection_id': self.connection.connection_id,
                'database': self.connection.database,
                'user': self.connection.user,
                'is_connected': self.is_connected()
            }
        except Exception as e:
            self.logger.error(f"Error getting connection info: {e}")
            return {}
    
    def close(self):
        """Close the database connection."""
        try:
            if self.connection and self.connection.is_connected():
                self.connection.close()
                self.logger.info("Database connection closed successfully")
        except Exception as e:
            self.logger.error(f"Error closing database connection: {e}")

def connect_to_database(config: Dict[str, str]) -> Optional[DatabaseManager]:
    """Create database connection and return DatabaseManager instance."""
    logger = logging.getLogger(__name__)
    
    try:
        # Prepare connection parameters
        connection_params = {
            'host': config.get('server', config.get('host')),
            'database': config['database'],
            'user': config['user'],
            'password': config['password'],
            'charset': config.get('charset', 'utf8mb4'),
            'collation': config.get('collation', 'utf8mb4_unicode_ci'),
            'autocommit': False,
            'raise_on_warnings': True,
            'sql_mode': 'STRICT_TRANS_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO',
            'connection_timeout': 30,
            'buffered': True
        }
        
        # Add SSL configuration if specified
        if config.get('use_ssl', '').lower() in ['true', '1', 'yes']:
            connection_params['ssl_disabled'] = False
        
        # Remove None values
        connection_params = {k: v for k, v in connection_params.items() if v is not None}
        
        logger.info(f"Attempting to connect to database: {connection_params['host']}/{connection_params['database']}")
        
        connection = mysql.connector.connect(**connection_params)
        
        if connection.is_connected():
            db_manager = DatabaseManager(connection)
            info = db_manager.get_connection_info()
            logger.info(f"Successfully connected to database - Server: {info.get('server_info', 'Unknown')}")
            return db_manager
        else:
            logger.error("Failed to establish database connection")
            return None
            
    except Error as e:
        logger.error(f"MySQL Error connecting to database: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error connecting to database: {e}")
        return None

def close_database_connection(db_manager: DatabaseManager):
    """Close database connection."""
    if db_manager:
        db_manager.close()

# Async versions for backward compatibility (though not truly async in this implementation)
async def connect_to_database_async(config: Dict[str, str]) -> Optional[mysql.connector.MySQLConnection]:
    """Create database connection (async version for backward compatibility)."""
    db_manager = connect_to_database(config)
    return db_manager.connection if db_manager else None

async def fetch_po_open_incomplete_vendor_wpqs(connection: mysql.connector.MySQLConnection) -> List[Dict[str, Any]]:
    """Fetch WPQs that are open and need vendor setup."""
    db_manager = DatabaseManager(connection)
    logger = logging.getLogger(__name__)
    
    try:
        query = """
        SELECT 
            sc.*,
            v.VendorSetupProcessCompleted,
            v.CompanyName,
            v.Email,
            v.Phone,
            v.CompanyResidentialAddress,
            v.CompanyCountry,
            v.CompanyTaxID,
            v.CompanyVatID,
            v.CompanyBankIBAN,
            v.CompanyBankName,
            v.CompanyBankSwift,
            v.CompanyBankID,
            v.CompanyBankBranch,
            v.CompanyBankAccountNumber,
            v.CompanyCurrencyType,
            v.FirstLanguage as VendorLanguage
        FROM sol_servicecalls sc
        LEFT JOIN sol_enterprise_vendors v ON sc.VendorID = v.ID
        WHERE sc.CallStatus IN (0, 20, 100, 110)
        AND sc.ActivityStatus = 1
        ORDER BY sc.CreationDate DESC
        """
        
        wpqs = db_manager.execute_query(query)
        if wpqs is None:
            return []
            
        logger.info(f"Fetched {len(wpqs)} open WPQs")
        
        # Check vendor setup status
        for wpq in wpqs:
            if not wpq.get('VendorSetupProcessCompleted'):
                wpq['vendor_setup_missing'] = []
                required_fields = [
                    ('CompanyName', 'Company Name'),
                    ('Email', 'Email'),
                    ('Phone', 'Phone'),
                    ('CompanyResidentialAddress', 'Address'),
                    ('CompanyCountry', 'Country'),
                    ('CompanyTaxID', 'Tax ID'),
                    ('CompanyVatID', 'VAT ID'),
                    ('CompanyCurrencyType', 'Currency Type')
                ]
                
                # Check bank details
                if not wpq.get('CompanyBankIBAN'):
                    bank_fields = [
                        ('CompanyBankName', 'Bank Name'),
                        ('CompanyBankSwift', 'Bank Swift'),
                        ('CompanyBankID', 'Bank ID'),
                        ('CompanyBankBranch', 'Bank Branch'),
                        ('CompanyBankAccountNumber', 'Account Number')
                    ]
                    required_fields.extend(bank_fields)
                
                # Add missing fields to the list
                for field, display_name in required_fields:
                    if not wpq.get(field):
                        wpq['vendor_setup_missing'].append(display_name)
        
        return wpqs

    except Exception as e:
        logger.error(f"Error fetching WPQs: {e}")
        return []

async def fetch_service_call_items(connection: mysql.connector.MySQLConnection, wpq_number: str) -> List[Dict[str, Any]]:
    """Fetch all items for a specific WPQ."""
    db_manager = DatabaseManager(connection)
    logger = logging.getLogger(__name__)
    
    try:
        query = """
        SELECT 
            ItemID,
            WPQNumber,
            ServiceTypeName as Category,
            ServiceDescription,
            CurrencyType as Currency,
            PurchasePrice as Price,
            Quantity,
            InitialExecutionDate,
            CurrentExecutionDate,
            RequestedExecutionDate,
            CustomerSku,
            VendorSku,
            RejectionStatus,
            RejectionComment
        FROM sol_servicecalls_items
        WHERE WPQNumber = %s
        ORDER BY ItemID
        """
        
        items = db_manager.execute_query(query, (wpq_number,))
        if items is None:
            return []
            
        logger.info(f"Fetched {len(items)} items for WPQ {wpq_number}")
        return items

    except Exception as e:
        logger.error(f"Error fetching items for WPQ {wpq_number}: {e}")
        return []

async def fetch_audit_logs(
    connection: mysql.connector.MySQLConnection,
    wpq_number: str
) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Fetch audit logs and identify last vendor setup and communication entries."""
    db_manager = DatabaseManager(connection)
    logger = logging.getLogger(__name__)
    
    try:
        query = """
        SELECT 
            ID,
            WPQNumber,
            AuditTypeID,
            Category,
            Service,
            ExecutionStatus,
            ActionStatus,
            Subject,
            Text,
            EnglishText,
            CreationDate,
            _MailID,
            TextB,
            TextBE
        FROM sol_servicecalls_audit_logs
        WHERE WPQNumber = %s
        ORDER BY CreationDate DESC
        """
        
        audit_logs = db_manager.execute_query(query, (wpq_number,))
        if audit_logs is None:
            return [], None, None
        
        # Get last vendor setup entry
        last_vendor_setup = next(
            (log for log in audit_logs if log.get('Category', '').lower().find('vendor setup') != -1),
            None
        )
        
        # Get last communication entry (Email=100, Call=200, WhatsApp=300, Support=400)
        last_communication = next(
            (log for log in audit_logs 
             if log.get('AuditTypeID') in [100, 200, 300, 400]),
            None
        )
        
        logger.info(f"Fetched {len(audit_logs)} audit logs for WPQ {wpq_number}")
        return audit_logs, last_vendor_setup, last_communication

    except Exception as e:
        logger.error(f"Error fetching audit logs for WPQ {wpq_number}: {e}")
        return [], None, None

def verify_vendor_setup(vendor_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Verify if vendor setup is complete and return missing fields."""
    missing_fields = []
    required_fields = {
        'CompanyName': 'Company Name',
        'Email': 'Email',
        'Phone': 'Phone',
        'CompanyResidentialAddress': 'Address',
        'CompanyCountry': 'Country',
        'CompanyTaxID': 'Tax ID',
        'CompanyVatID': 'VAT ID',
        'CompanyCurrencyType': 'Currency Type'
    }
    
    # Check main fields
    for field, display_name in required_fields.items():
        if not vendor_data.get(field):
            missing_fields.append(display_name)
    
    # Check bank details
    if not vendor_data.get('CompanyBankIBAN'):
        bank_fields = {
            'CompanyBankName': 'Bank Name',
            'CompanyBankSwift': 'Bank Swift',
            'CompanyBankID': 'Bank ID',
            'CompanyBankBranch': 'Bank Branch',
            'CompanyBankAccountNumber': 'Account Number'
        }
        for field, display_name in bank_fields.items():
            if not vendor_data.get(field):
                missing_fields.append(display_name)
    
    return len(missing_fields) == 0, missing_fields

def test_database_connection(config: Dict[str, str]) -> bool:
    """Test database connection and return success status."""
    logger = logging.getLogger(__name__)
    
    try:
        db_manager = connect_to_database(config)
        if not db_manager:
            return False
        
        # Try a simple query
        result = db_manager.execute_query("SELECT 1 as test")
        success = result is not None and len(result) > 0
        
        if success:
            logger.info("Database connection test successful")
        else:
            logger.error("Database connection test failed - query returned no results")
        
        db_manager.close()
        return success
        
    except Exception as e:
        logger.error(f"Database connection test failed: {e}")
        return False

# Connection pool support (basic implementation)
class ConnectionPool:
    """Simple connection pool for database connections."""
    
    def __init__(self, config: Dict[str, str], pool_size: int = 5):
        self.config = config
        self.pool_size = pool_size
        self.pool = []
        self.logger = logging.getLogger(__name__)
    
    def get_connection(self) -> Optional[DatabaseManager]:
        """Get a connection from the pool."""
        # Simple implementation - always create new connection
        # In production, you might want to implement actual pooling
        return connect_to_database(self.config)
    
    def return_connection(self, db_manager: DatabaseManager):
        """Return a connection to the pool."""
        # Simple implementation - just close the connection
        db_manager.close()

# Initialize logging when module is imported
setup_database_logging()