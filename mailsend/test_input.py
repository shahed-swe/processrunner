#!/usr/bin/env python3
# test_input.py - Simple script to test input parameter passing

print("Select environment:")
print("1. Production")
print("2. Development")
choice = input("Enter choice (1/2): ").strip()

if choice == '1':
    env = 'Production'
elif choice == '2':
    env = 'Database'
else:
    env = 'Unknown'

print(f"Selected environment: {env}")

test_mode = input("Is this a test run? (y/n): ").lower().strip() == 'y'
print(f"Test mode: {test_mode}")

print(f"Parameters received successfully:")
print(f"  Environment: {env}")
print(f"  Test mode: {test_mode}")
print("Script completed!")
