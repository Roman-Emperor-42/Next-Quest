import random
import requests
import time
import threading
from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for, current_app
)

from flaskr.auth import login_required
from flaskr.db import get_db

bp = Blueprint('steam', __name__, url_prefix='/steam')


def get_steam_api_key():
    """Get Steam API key from config or environment variable."""
    from flask import current_app
    import os
    return current_app.config.get('STEAM_API_KEY') or os.environ.get('STEAM_API_KEY')


def resolve_steam_id(steam_id_input):
    """
    Resolve Steam ID from various formats (vanity URL, Steam ID64, etc.)
    Returns (steam_id64, error_message) tuple. steam_id64 is string or None.
    """
    api_key = get_steam_api_key()
    if not api_key:
        return None, 'Steam API key is not configured. Please set STEAM_API_KEY environment variable or add it to config.py'
    
    # Clean the input - remove common Steam profile URL patterns
    steam_id_input = steam_id_input.strip()
    # Remove https://steamcommunity.com/profiles/ prefix
    if 'steamcommunity.com/profiles/' in steam_id_input:
        steam_id_input = steam_id_input.split('steamcommunity.com/profiles/')[-1].split('/')[0]
    # Remove https://steamcommunity.com/id/ prefix
    elif 'steamcommunity.com/id/' in steam_id_input:
        steam_id_input = steam_id_input.split('steamcommunity.com/id/')[-1].split('/')[0]
    
    # If it's already numeric, validate it's a valid Steam ID64 (should be 17 digits)
    if steam_id_input.isdigit():
        if len(steam_id_input) == 17:
            return steam_id_input, None
        else:
            return None, f'Invalid Steam ID format. Steam ID64 should be 17 digits, got {len(steam_id_input)} digits.'
    
    # Try to resolve as vanity URL
    try:
        url = "http://api.steampowered.com/ISteamUser/ResolveVanityURL/v0001/"
        params = {
            'key': api_key,
            'vanityurl': steam_id_input
        }
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        response_data = data.get('response', {})
        if response_data.get('success') == 1:
            return response_data.get('steamid'), None
        elif response_data.get('success') == 42:
            return None, f'Vanity URL "{steam_id_input}" not found. Please check your Steam profile username.'
        else:
            return None, f'Failed to resolve vanity URL. Steam API returned: {response_data}'
    except requests.RequestException as e:
        return None, f'Error connecting to Steam API: {str(e)}'
    except Exception as e:
        return None, f'Unexpected error resolving Steam ID: {str(e)}'


def fetch_steam_library(steam_id):
    """
    Fetch user's Steam library using Steam Web API.
    Returns (games_list, error_message) tuple. games_list is list or None.
    """
    api_key = get_steam_api_key()
    if not api_key:
        return None, 'Steam API key is not configured.'
    
    try:
        url = "http://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/"
        params = {
            'key': api_key,
            'steamid': steam_id,
            'format': 'json',
            'include_appinfo': True,
            'include_played_free_games': True
        }
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if 'response' in data:
            if 'games' in data['response']:
                return data['response']['games'], None
            elif 'game_count' in data['response'] and data['response']['game_count'] == 0:
                return [], None
            else:
                # Check for error in response
                error_msg = data['response'].get('error', 'Unknown error from Steam API')
                return None, f'Steam API error: {error_msg}'
        return [], None
    except requests.HTTPError as e:
        if e.response.status_code == 403:
            return None, 'Access denied. Your Steam profile may be private. Please set your profile to public in Steam settings.'
        return None, f'HTTP error fetching Steam library: {e.response.status_code} - {e.response.text[:200]}'
    except requests.RequestException as e:
        return None, f'Error connecting to Steam API: {str(e)}'
    except Exception as e:
        return None, f'Unexpected error: {str(e)}'


def get_game_details(appid, retry_count=0):
    """
    Get game details from Steam Store API.
    Returns game info dict or None.
    """
    try:
        url = f"https://store.steampowered.com/api/appdetails"
        params = {
            'appids': appid,
            'l': 'en'
        }
        response = requests.get(url, params=params, timeout=10)
        
        # Handle rate limiting
        if response.status_code == 429:
            if retry_count < 3:
                # Wait longer with each retry (exponential backoff)
                wait_time = (2 ** retry_count) * 2  # 2s, 4s, 8s
                time.sleep(wait_time)
                return get_game_details(appid, retry_count + 1)
            else:
                print(f"Rate limited for game {appid} after {retry_count} retries")
                return None
        
        response.raise_for_status()
        data = response.json()
        
        if str(appid) in data and data[str(appid)]['success']:
            return data[str(appid)]['data']
        return None
    except requests.RequestException as e:
        if "429" not in str(e):  # Don't print rate limit errors, we handle them above
            print(f"Error fetching game details: {e}")
        return None


def fetch_tags_background(app, games_to_tag):
    """
    Background function to fetch tags for games.
    Runs in a separate thread to avoid blocking the import.
    """
    with app.app_context():
        import sqlite3
        from flask import current_app
        
        # Create a new database connection for this thread
        db_path = current_app.config['DATABASE']
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        db = conn
        
        tagged_count = 0
        
        try:
            for game_info in games_to_tag:
                try:
                    # Add delay between requests to avoid rate limiting
                    # Steam allows ~200 requests per 5 minutes, so ~1 request per 1.5 seconds is safe
                    time.sleep(1.5)
                    
                    appid = game_info['appid']
                    game_id = game_info['game_id']
                    
                    steam_tags = get_game_tags_from_steam(appid)
                    if steam_tags:
                        # Remove existing tags for this game
                        db.execute('DELETE FROM game_tag WHERE game_id = ?', (game_id,))
                        
                        # Add new tags
                        for tag in steam_tags:
                            try:
                                db.execute(
                                    'INSERT INTO game_tag (game_id, tag) VALUES (?, ?)',
                                    (game_id, tag)
                                )
                            except sqlite3.IntegrityError:
                                pass  # Tag already exists
                        tagged_count += 1
                        db.commit()
                except Exception as e:
                    # If we hit rate limits, wait longer and continue
                    if "429" in str(e) or "Too Many Requests" in str(e):
                        print(f"Rate limited for game {appid}, waiting longer...")
                        time.sleep(10)  # Wait 10 seconds before continuing
                    else:
                        print(f"Error fetching tags for game {appid}: {e}")
        finally:
            conn.close()
        
        print(f"Background tag fetching completed. Tagged {tagged_count} games.")


def get_game_tags_from_steam(appid):
    """
    Get game tags from Steam Store API.
    Returns list of tag strings or empty list.
    """
    try:
        game_details = get_game_details(appid)
        if not game_details:
            return []
        
        tags = []
        
        # Steam API returns genres
        if 'genres' in game_details:
            for genre in game_details['genres']:
                if 'description' in genre:
                    tags.append(genre['description'])
        
        # Get categories (these include tags like "Single-player", "Multi-player", etc.)
        if 'categories' in game_details:
            for category in game_details['categories']:
                if 'description' in category:
                    cat_desc = category['description']
                    # Map Steam categories to our tag system
                    if 'Single-player' in cat_desc:
                        tags.append('Singleplayer')
                    elif 'Multi-player' in cat_desc:
                        tags.append('Multiplayer')
                    elif 'Co-op' in cat_desc:
                        tags.append('Co-op')
                    elif 'Competitive' in cat_desc:
                        tags.append('Competitive')
        
        # Normalize tags to match our POPULAR_TAGS list
        # These should match the tags in recommendations.py
        POPULAR_TAGS = [
            'Action', 'Adventure', 'RPG', 'Strategy', 'Simulation', 'Sports',
            'Racing', 'Puzzle', 'Indie', 'Casual', 'Multiplayer', 'Singleplayer',
            'FPS', 'Horror', 'Sci-Fi', 'Fantasy', 'Open World', 'Story Rich',
            'Co-op', 'Competitive', 'Sandbox', 'Survival', 'Crafting', 'Building'
        ]
        normalized_tags = []
        tag_mapping = {
            'Action': 'Action',
            'Adventure': 'Adventure',
            'RPG': 'RPG',
            'Role-playing': 'RPG',
            'Strategy': 'Strategy',
            'Simulation': 'Simulation',
            'Sports': 'Sports',
            'Racing': 'Racing',
            'Puzzle': 'Puzzle',
            'Indie': 'Indie',
            'Casual': 'Casual',
            'First-Person Shooter': 'FPS',
            'FPS': 'FPS',
            'Horror': 'Horror',
            'Sci-Fi': 'Sci-Fi',
            'Science Fiction': 'Sci-Fi',
            'Fantasy': 'Fantasy',
            'Open World': 'Open World',
            'Story Rich': 'Story Rich',
            'Co-op': 'Co-op',
            'Cooperative': 'Co-op',
            'Competitive': 'Competitive',
            'Sandbox': 'Sandbox',
            'Survival': 'Survival',
            'Crafting': 'Crafting',
            'Building': 'Building',
            'Single-player': 'Singleplayer',
            'Singleplayer': 'Singleplayer',
            'Multi-player': 'Multiplayer',
            'Multiplayer': 'Multiplayer'
        }
        
        for tag in tags:
            # Try exact match first
            if tag in tag_mapping:
                normalized = tag_mapping[tag]
                if normalized in POPULAR_TAGS and normalized not in normalized_tags:
                    normalized_tags.append(normalized)
            # Try case-insensitive match
            else:
                tag_lower = tag.lower()
                for key, value in tag_mapping.items():
                    if key.lower() == tag_lower:
                        if value in POPULAR_TAGS and value not in normalized_tags:
                            normalized_tags.append(value)
                        break
        
        return normalized_tags
    except Exception as e:
        print(f"Error fetching game tags for appid {appid}: {e}")
        return []


@bp.route('/import', methods=('GET', 'POST'))
@login_required
def import_library():
    """Import user's Steam library."""
    if request.method == 'POST':
        steam_id_input = request.form.get('steam_id', '').strip()
        error = None
        
        if not steam_id_input:
            error = 'Steam ID or vanity URL is required.'
        
        if error is None:
            # Resolve Steam ID
            steam_id, resolve_error = resolve_steam_id(steam_id_input)
            if resolve_error:
                error = resolve_error
            elif not steam_id:
                error = 'Invalid Steam ID or vanity URL. Please check your input.'
        
        if error is None:
            # Fetch library
            games, fetch_error = fetch_steam_library(steam_id)
            if fetch_error:
                error = fetch_error
            elif games is None:
                error = 'Failed to fetch Steam library. Please check your Steam ID and API key.'
            elif len(games) == 0:
                error = 'No games found in your Steam library.'
        
        if error is None:
            db = get_db()
            imported_count = 0
            updated_count = 0
            tag_fetch_enabled = request.form.get('fetch_tags', 'true') == 'true'
            games_to_tag = []  # Store games that need tags fetched
            
            for game_data in games:
                appid = game_data.get('appid')
                name = game_data.get('name', 'Unknown Game')
                playtime = game_data.get('playtime_forever', 0)
                img_icon_url = game_data.get('img_icon_url', '')
                img_logo_url = game_data.get('img_logo_url', '')
                
                # Insert or update game
                try:
                    db.execute(
                        'INSERT INTO game (appid, name, platform, playtime_forever, img_icon_url, img_logo_url)'
                        ' VALUES (?, ?, ?, ?, ?, ?)',
                        (str(appid), name, 'steam', playtime, img_icon_url, img_logo_url)
                    )
                except db.IntegrityError:
                    # Game already exists, update it
                    db.execute(
                        'UPDATE game SET name = ?, playtime_forever = ?,'
                        ' img_icon_url = ?, img_logo_url = ? WHERE appid = ? AND platform = ?',
                        (name, playtime, img_icon_url, img_logo_url, str(appid), 'steam')
                    )
                    updated_count += 1
                else:
                    imported_count += 1
                
                # Get game ID
                game = db.execute(
                    'SELECT id FROM game WHERE appid = ? AND platform = ?', (str(appid), 'steam')
                ).fetchone()
                
                # Store game info for background tag fetching
                if tag_fetch_enabled:
                    games_to_tag.append({
                        'game_id': game['id'],
                        'appid': appid
                    })
                
                # Insert or update user_game_library
                try:
                    db.execute(
                        'INSERT INTO user_game_library (user_id, game_id, playtime_forever)'
                        ' VALUES (?, ?, ?)',
                        (g.user['id'], game['id'], playtime)
                    )
                except db.IntegrityError:
                    # Already in library, update playtime
                    db.execute(
                        'UPDATE user_game_library SET playtime_forever = ?,'
                        ' imported_at = CURRENT_TIMESTAMP'
                        ' WHERE user_id = ? AND game_id = ?',
                        (playtime, g.user['id'], game['id'])
                    )
            
            db.commit()
            
            # Start background thread to fetch tags
            if tag_fetch_enabled and games_to_tag:
                thread = threading.Thread(
                    target=fetch_tags_background,
                    args=(current_app._get_current_object(), games_to_tag),
                    daemon=True
                )
                thread.start()
                message = f'Successfully imported {imported_count} new games and updated {updated_count} existing games! Tags are being fetched in the background.'
            else:
                message = f'Successfully imported {imported_count} new games and updated {updated_count} existing games!'
            
            flash(message)
            return redirect(url_for('steam.library'))
        
        flash(error)
    
    return render_template('steam/import.html')


@bp.route('/library')
@login_required
def library():
    """Display user's imported Steam library."""
    db = get_db()
    
    # Get sort parameter from query string
    sort_by = request.args.get('sort', 'name')
    sort_order = request.args.get('order', 'asc')
    
    # Validate sort parameters
    valid_sorts = {
        'name': 'g.name',
        'playtime': 'ugl.playtime_forever',
        'imported': 'ugl.imported_at'
    }
    valid_orders = ['asc', 'desc']
    
    if sort_by not in valid_sorts:
        sort_by = 'name'
    if sort_order not in valid_orders:
        sort_order = 'asc'
    
    # Build ORDER BY clause safely using whitelist
    order_column = valid_sorts[sort_by]
    order_direction = sort_order.upper()
    order_clause = f"{order_column} {order_direction}"
    
    games = db.execute(
        'SELECT g.id, g.appid, g.name, g.platform, g.playtime_forever, g.img_icon_url, g.img_logo_url,'
        ' ugl.imported_at, ugl.playtime_forever as user_playtime'
        ' FROM user_game_library ugl'
        ' JOIN game g ON ugl.game_id = g.id'
        ' WHERE ugl.user_id = ?'
        f' ORDER BY {order_clause}',
        (g.user['id'],)
    ).fetchall()
    
    # Get highlighted game ID from query parameter
    highlight_id = request.args.get('highlight', type=int)
    
    return render_template('steam/library.html', games=games, sort_by=sort_by, sort_order=sort_order, highlight_id=highlight_id)


@bp.route('/library/random')
@login_required
def random_game():
    """Select a random game from user's library."""
    db = get_db()
    
    games = db.execute(
        'SELECT g.id, g.appid, g.name'
        ' FROM user_game_library ugl'
        ' JOIN game g ON ugl.game_id = g.id'
        ' WHERE ugl.user_id = ?',
        (g.user['id'],)
    ).fetchall()
    
    if not games:
        flash('Your library is empty. Import games first!')
        return redirect(url_for('steam.library'))
    
    # Select a random game
    selected_game = random.choice(games)
    
    # Flash message with the selected game
    flash(f"🎲 Random game selected: {selected_game['name']}")
    
    # Redirect back to library with the selected game ID as a parameter
    return redirect(url_for('steam.library', highlight=selected_game['id']))


@bp.route('/library/<int:game_id>/remove', methods=('POST',))
@login_required
def remove_game(game_id):
    """Remove a game from user's library."""
    db = get_db()
    db.execute(
        'DELETE FROM user_game_library WHERE user_id = ? AND game_id = ?',
        (g.user['id'], game_id)
    )
    db.commit()
    flash('Game removed from your library.')
    return redirect(url_for('steam.library'))

