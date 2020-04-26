import sys
def version_check():
    if sys.version_info.major < 3:
        string = "The script may not work with Python version 3.7 and below \n"
        string += "Execute the script with Python 3.8 \n"
        string += "Press enter to continue"
        input(string)
