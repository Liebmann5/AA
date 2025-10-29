"""
A utility to detect the user's current operating system and platform.
"""
import sys
import platform

def get_os():
    """Returns the name of the operating system."""
    return sys.platform

def get_system_details():
    """Returns a more detailed platform string."""
    return platform.platform()

def is_mobile():
    """
    A simple check to determine if the environment might be mobile.
    In a real mobile environment, this would be more complex, often
    relying on environment variables set by tools like Kivy or BeeWare.
    For our purposes, we can simulate this.
    """
    return "android" in get_system_details().lower()