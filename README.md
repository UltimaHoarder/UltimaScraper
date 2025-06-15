# UltimaScraper

UltimaScraper is a Python-based scraper for various content platforms. It allows users to download content from selected sites based on their configuration.

## Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/ultimascraper/ultima-scraper.git
    cd ultima-scraper
    ```

2.  **Install dependencies:**
    It is recommended to use a virtual environment.
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```
    Install the required packages:
    ```bash
    pip install -r requirements.txt
    ```

## Running the Scraper

To run the scraper, execute the `start_us.py` script:

```bash
python start_us.py
```

You will be prompted to choose the site you want to scrape if not configured for automatic choice.

## Configuration

The scraper's behavior is controlled by a `config.json` file located in the `ultima_scraper_settings/settings` directory. If this file or directory structure does not exist, the scraper will likely create it with default values on the first run.

### Main Configuration Options (`config.json`):

The `config.json` file typically contains settings related to:

*   **`settings`**: Global settings for the scraper.
    *   **`auto_site_choice`**: Set to a specific site name (e.g., "OnlyFans", "Fansly") to automatically select that site, or leave empty/null to be prompted.
    *   **`infinite_loop`**: `true` to run the scraper continuously, `false` to run once.
    *   **`loop_timeout`**: Number of seconds to wait between runs if `infinite_loop` is `true`.
    *   **`exit_on_completion`**: `true` to exit the script after the current scraping job is done, `false` to wait for user input or loop.
    *   **`proxies`**: Configure proxy settings if needed.
    *   **`webhooks`**: Configure webhook URLs for notifications.
    *   **Other settings**: Refer to `ultima_scraper_api.classes.make_settings.GlobalSettings` for more details.

*   **`supported`**: A dictionary listing supported sites and their specific configurations. For each site (e.g., "OnlyFans", "Fansly"):
    *   **`auth`**: Authentication details.
        *   **`username`**: Your username for the site.
        *   **`password`**: Your password for the site (handle with care).
        *   **`sess`**: Session cookie.
        *   **`user_agent`**: User agent string for requests.
        *   **`auth_id`**: Authentication ID.
        *   **Other auth-related fields**: Specific to the site's authentication mechanism.
    *   **`auto_profile_choice`**: Automatically select profiles if set.
    *   **`auto_model_choice`**: Automatically select models/performers to scrape.
    *   **`auto_api_choice`**: Automatically select content types to scrape (e.g., "Posts", "Messages").
    *   **`auto_media_choice`**: Automatically select media types to download (e.g., "Images", "Videos").
    *   **Other site-specific settings**: Refer to `ultima_scraper_api.classes.make_settings.SiteSettings` for more details.

**Note:** You will need to manually create or edit the `ultima_scraper_settings/settings/config.json` file with your authentication details and preferences. The scraper might guide you through creating parts of this configuration or authenticating interactively for the first time.

### Profile-Specific Authentication

For sites like OnlyFans and Fansly, authentication details are often stored in a user-specific `auth.json` file within the `ultima_scraper_settings/profiles/[site_name]/[username]/auth.json` directory. The scraper will use these files to log in.

## Usage Examples

1.  **First-time run / Interactive setup:**
    If `config.json` is missing or `auto_site_choice` is not set, running `python start_us.py` will typically prompt you to select a site. For sites requiring login, it might open a browser or ask for credentials to perform the initial authentication.

2.  **Automatic scraping of a specific site:**
    Modify `ultima_scraper_settings/settings/config.json`:
    ```json
    {
        "settings": {
            "auto_site_choice": "OnlyFans",
            "infinite_loop": false,
            "exit_on_completion": true
            // ... other global settings
        },
        "supported": {
            "OnlyFans": {
                // ... your OnlyFans auth and site settings ...
                "auto_model_choice": "all" // Example: scrape all subscribed models
            },
            "Fansly": {
                // ... your Fansly auth and site settings ...
            }
        }
    }
    ```
    Then run:
    ```bash
    python start_us.py
    ```
    This will automatically start scraping OnlyFans content based on your configuration and then exit.

3.  **Continuous scraping with a pause:**
    Modify `ultima_scraper_settings/settings/config.json`:
    ```json
    {
        "settings": {
            "auto_site_choice": "Fansly",
            "infinite_loop": true,
            "loop_timeout": 3600, // Pause for 1 hour (3600 seconds)
            "exit_on_completion": false
            // ... other global settings
        },
        "supported": {
            "OnlyFans": {
                // ...
            },
            "Fansly": {
                // ... your Fansly auth and site settings ...
                "auto_api_choice": ["Posts", "Messages"], // Example: scrape posts and messages
                "auto_model_choice": ["model_username1", "model_username2"] // Example: scrape specific models
            }
        }
    }
    ```
    Run the scraper. It will scrape Fansly, wait for an hour, and then repeat.

## Disclaimer

This tool is intended for personal use and for downloading content that you have legitimate access to. Respect the terms of service of the platforms you are using this tool with. The developers are not responsible for misuse of this tool.
