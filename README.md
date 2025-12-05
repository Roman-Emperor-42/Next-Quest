# Next-Quest

Finding new video games that match your interests can be difficult due to the vast amount of games. Our project strives to build a recommendation system that builds off of what you currently play and other users' reviews.

## Description

We propose building a video game recommendation system where users create profiles, import profiles, input preferences, and receive personalized game suggestions. At a higher level, the system will store user data, apply recommendations, and display results in a simple UI. The target users are gamers looking for new games that don’t want to sift through the endless pages of game stores.


## Authors

Contributors names and contact info

 [Caleb Graham](https://github.com/Roman-Emperor-42)
 
 [Joe Hayes]()
 
 [Lee Vera]()

## Installing/Using

In Terminal/Command line navigate to the directory you cloned to and run the command (src)

```pip install -e .```

### API Setup

#### Steam API Setup

To use the Steam library importer, you need a Steam Web API key:

1. Get your Steam API key from [Steam Web API Key](https://steamcommunity.com/dev/apikey)
2. Set it as an environment variable:
   ```bash
   export STEAM_API_KEY=your_api_key_here
   ```
   Or add it to your Flask instance config in `instance/config.py`:
   ```python
   STEAM_API_KEY = 'your_api_key_here'
   ```

### Running the Application

you can now run the project with the command (debug is optional)

```flask --app flaskr init-db```

```flask --app flaskr run --debug```

This will host the app locally at https://127.0.0.1:5000. any changes you make will update on the local dev site in real time.

### Using the Steam Library Importer

1. Log in to your account
2. Navigate to "My Library" in the navigation menu
3. Click "Import from Steam"
4. Enter your Steam ID (found at [steamid.io](https://steamid.io)) or your Steam profile username
5. Your library will be imported and displayed

## License

This project is licensed under the MIT License - see the LICENSE.md file for details
