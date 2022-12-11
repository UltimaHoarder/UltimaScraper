# Running the DataScraper on Linux

This programs run in CLI (Terminal). There is no GUI currently available.
This is for Ubuntu Focal Fossa and Hirsute.

## Install and update scraper code the simple way

### First Time Installation

1. Make sure to have unzip installed
`sudo apt update && sudo apt -y install unzip`

2. Go to the directory where you want the code to be stored

3. Download the code

	`wget https://github.com/DIGITALCRIMINALS/OnlyFans/archive/refs/heads/master.zip`

4. Unzip the code, rename it and remove the original zip file

	`unzip master.zip && mv OnlyFans-master onlyfans && rm master.zip`

5. Enter our new directory

	`cd onlyfans`

6. Go to the [Installation of Python](#Installation-of-Python) section and complete it.

### Updating Scraper
Once you have completed the installation of python section, follow the follwing steps in order

1. Be in the directory where the scraper is at.

2. Activate Virtual Enviroment

	`source venv/bin/activate`

3. Run the updater program

	`python3 updater.py`
	
4. Deactivate Virtual Enviroment
	
	`deactivate`
	
## Install and update scraper using Git

**WARNING: This method is not suggested for users who just want to use the scraper. Git is meant for devlopment purposes.**

### Installing git
Make sure you have git installed

	`sudo apt update && sudo apt -y install git`

### First Time Installation
1. Go to the directory where you would like the code.

2. Clone the repository.

	`git clone https://github.com/DIGITALCRIMINALS/OnlyFans`

### Updating the Repository
** This does not work if you have changed any of the files that are being updated yourself.**
1. Be in the directory of the code you are in

2. Update code

	`git pull`

If you have changed files and want the new update to "overwrite" them run the following command

'git stash'

## Installation of Python

1. Install Python3.10

	`sudo apt update && sudo apt -y install python3.10`

2. Install the Python3.10 Virtual Enviroment

	`sudo apt -y install python3.10-dev python3.10-venv`

3. Make our Python Virtual Enviroment

	`python3.10 -m venv venv`

4. Enter our virtual enviroment

	`source venv/bin/activate`

We now are inside of our python3.10 virtual enviroment. This makes it so that other programs won't screw with our scraper and our scraper won't screw with your other programs or virtual enviroments

5. Install Requiremtents

	`pip install poetry`
	
	`poetry install --no-dev`

6. Exit Virtual Enviroment

	`deactivate`

You have just installed the scraper! Congratulations!

## Updates
Updates are necessary to keep up with new reqirements and to keep up with what the main site is doing. Please go to the installation section you used to install the Scraper

## Running
Follow the steps in order every time we use the scraper

1. Be in the Directory where the code is.

2. Activate our virtual Enviroment

	`source venv/bin/activate`

3. Run The Scraper

	`python3 start_ofd.py`

4. Do what the program says. Remember to type the apropriate numbers. If you need to do some configuration, it is ok to pres CTRL + C. After configuring, go back to step 3.

5. After the Scraper is finished or you need to exit the virtual enviroment, run the following command to make things 'normal'

	`deactivate`
