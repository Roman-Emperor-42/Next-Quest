import random
import requests
from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for
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


def get_game_details(appid):
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
        response.raise_for_status()
        data = response.json()
        
        if str(appid) in data and data[str(appid)]['success']:
            return data[str(appid)]['data']
        return None
    except requests.RequestException as e:
        print(f"Error fetching game details: {e}")
        return None


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
            flash(f'Successfully imported {imported_count} new games and updated {updated_count} existing games!')
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

