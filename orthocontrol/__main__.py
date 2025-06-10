# ABOUTME: Entry point for running orthocontrol as a module
# ABOUTME: Allows execution via python -m orthocontrol

import sys
import os
import importlib.util

# Get the path to orthocontrol.py in the parent directory
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
orthocontrol_path = os.path.join(parent_dir, 'orthocontrol.py')

# Load the module from the file
spec = importlib.util.spec_from_file_location("orthocontrol_main", orthocontrol_path)
orthocontrol_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(orthocontrol_main)

if __name__ == "__main__":
    orthocontrol_main.main()