import sys
import os


def start():
    print

try:
    if __name__ == "__main__":
        cwd = os.getcwd()
        cwd2 = os.path.dirname(__file__)
        if cwd == cwd2:
            x = os.path.realpath('../../../')
        else:
            x = os.path.realpath('')
        sys.path.insert(0, x)
        while True:
            from helpers.db_helper import database_collection, run_revisions
            db_collection = database_collection()
            key_list = db_collection.__dict__.items()
            key_list = list(key_list)
            string = f""
            count = 0
            for key, item in key_list:
                print
                string += f"{str(count)} = {key} | "
                count += 1
            print(string)
            x = input()
            # x = 0
            x = int(x)
            database_path = None
            module = key_list[x][1]
            if module:
                api_type = os.path.basename(module.__file__)
                database_path = module.__file__
                filename = f"test_{api_type}"
                filename = filename.replace("py", "db")
                database_directory = os.path.dirname(database_path)
                final_database_path = os.path.join(database_directory, filename)
                alembic_directory = database_directory
                run_revisions(alembic_directory, final_database_path)
                print("DONE")
            else:
                print("Failed")
except Exception as e:
    input(e)
