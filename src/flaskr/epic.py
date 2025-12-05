import random
import requests
import base64
import json
import re
from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for
)

from flaskr.auth import login_required
from flaskr.db import get_db

bp = Blueprint('epic', __name__, url_prefix='/epic')


def get_epic_api_credentials():
    """Get Epic Games API credentials from config or environment variables."""
    from flask import current_app
    import os
    return {
        'client_id': current_app.config.get('EPIC_CLIENT_ID') or os.environ.get('EPIC_CLIENT_ID'),
        'client_secret': current_app.config.get('EPIC_CLIENT_SECRET') or os.environ.get('EPIC_CLIENT_SECRET'),
        'deployment_id': current_app.config.get('EPIC_DEPLOYMENT_ID') or os.environ.get('EPIC_DEPLOYMENT_ID', 'prod'),
    }


def get_epic_access_token():
    """
    Get OAuth access token from Epic Games using client credentials flow.
    Returns access token or None if error.
    """
    credentials = get_epic_api_credentials()
    
    if not credentials['client_id'] or not credentials['client_secret']:
        return None, 'Epic Games API credentials not configured. Please set EPIC_CLIENT_ID and EPIC_CLIENT_SECRET.'
    
    try:
        # Epic Games OAuth token endpoint
        url = "https://api.epicgames.dev/epic/oauth/v2/token"
        
        # Client credentials grant
        auth_string = f"{credentials['client_id']}:{credentials['client_secret']}"
        auth_header = base64.b64encode(auth_string.encode()).decode()
        
        headers = {
            'Authorization': f'Basic {auth_header}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        data = {
            'grant_type': 'client_credentials',
            'deployment_id': credentials['deployment_id']
        }
        
        response = requests.post(url, headers=headers, data=data, timeout=10)
        response.raise_for_status()
        
        token_data = response.json()
        return token_data.get('access_token'), None
        
    except requests.RequestException as e:
        return None, f'Error getting Epic Games access token: {str(e)}'


def fetch_epic_library(account_id, access_token):
    """
    Fetch user's Epic Games library using Epic Games Ecom API.
    Returns (games_list, error_message) tuple.
    """
    if not access_token:
        return None, 'No access token available.'
    
    try:
        # Epic Games Ecom API endpoint for user entitlements
        url = f"https://api.epicgames.dev/epic/ecom/v1/accounts/{account_id}/entitlements"
        
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        params = {
            'includeRedeemed': True
        }
        
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        # Parse entitlements into game list
        games = []
        for item in data.get('items', []):
            if item.get('type') == 'ENTITLEMENT':
                offer = item.get('offer', {})
                games.append({
                    'id': item.get('id'),
                    'offer_id': offer.get('id'),
                    'name': offer.get('title', 'Unknown Game'),
                    'namespace': offer.get('namespace'),
                })
        
        return games, None
        
    except requests.HTTPError as e:
        if e.response.status_code == 401:
            return None, 'Authentication failed. Please check your Epic Games API credentials.'
        elif e.response.status_code == 403:
            return None, 'Access denied. You may need partner access to use the Epic Games Ecom API.'
        return None, f'HTTP error fetching Epic Games library: {e.response.status_code}'
    except requests.RequestException as e:
        return None, f'Error connecting to Epic Games API: {str(e)}'


def get_epic_game_details(offer_id):
    """
    Get game details from Epic Games Store API.
    Returns game info dict or None.
    """
    try:
        # Epic Games catalog API
        url = f"https://catalog-public-service-prod.ol.epicgames.com/catalog/api/shared/namespace/fn/items/{offer_id}"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            return response.json()
        return None
    except requests.RequestException as e:
        print(f"Error fetching Epic game details: {e}")
        return None


def parse_epic_manifest(manifest_data):
    """
    Parse Epic Games launcher manifest data.
    Epic Games stores library data in JSON format.
    Returns list of games or None if error.
    """
    try:
        # Try to parse as JSON
        if isinstance(manifest_data, str):
            data = json.loads(manifest_data)
        else:
            data = manifest_data
        
        games = []
        
        # Handle different manifest formats
        # Format 1: Array of game objects
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    game_name = item.get('AppName') or item.get('DisplayName') or item.get('name') or item.get('title')
                    app_id = item.get('AppId') or item.get('AppID') or item.get('appId') or item.get('id')
                    namespace = item.get('Namespace') or item.get('namespace')
                    
                    if game_name:
                        games.append({
                            'name': game_name,
                            'app_id': app_id,
                            'namespace': namespace,
                            'offer_id': item.get('OfferId') or item.get('offerId') or app_id
                        })
        
        # Format 2: Object with games array
        elif isinstance(data, dict):
            # Check for common keys
            games_list = data.get('games') or data.get('Items') or data.get('items') or data.get('library')
            
            if games_list:
                for item in games_list:
                    if isinstance(item, dict):
                        game_name = item.get('AppName') or item.get('DisplayName') or item.get('name') or item.get('title')
                        app_id = item.get('AppId') or item.get('AppID') or item.get('appId') or item.get('id')
                        namespace = item.get('Namespace') or item.get('namespace')
                        
                        if game_name:
                            games.append({
                                'name': game_name,
                                'app_id': app_id,
                                'namespace': namespace,
                                'offer_id': item.get('OfferId') or item.get('offerId') or app_id
                            })
            else:
                # Try to extract games from any nested structure
                for key, value in data.items():
                    if isinstance(value, list):
                        for item in value:
                            if isinstance(item, dict):
                                game_name = item.get('AppName') or item.get('DisplayName') or item.get('name') or item.get('title')
                                if game_name:
                                    games.append({
                                        'name': game_name,
                                        'app_id': item.get('AppId') or item.get('AppID') or item.get('appId') or item.get('id'),
                                        'namespace': item.get('Namespace') or item.get('namespace'),
                                        'offer_id': item.get('OfferId') or item.get('offerId')
                                    })
        
        return games if games else None
        
    except json.JSONDecodeError:
        # Try to extract game names from plain text
        games = []
        lines = manifest_data.split('\n') if isinstance(manifest_data, str) else []
        for line in lines:
            line = line.strip()
            if line and not line.startswith('#'):
                # Try to extract JSON-like structures
                match = re.search(r'"([^"]+)"\s*:\s*"([^"]+)"', line)
                if match:
                    key, value = match.groups()
                    if 'name' in key.lower() or 'title' in key.lower() or 'app' in key.lower():
                        games.append({'name': value, 'app_id': None, 'namespace': None, 'offer_id': None})
        return games if games else None
    except Exception as e:
        print(f"Error parsing Epic manifest: {e}")
        return None


@bp.route('/import/manifest', methods=('GET', 'POST'))
@login_required
def import_manifest():
    """Import Epic Games library from manifest file or pasted data."""
    if request.method == 'POST':
        manifest_text = request.form.get('manifest_text', '').strip()
        error = None
        
        if not manifest_text:
            error = 'Please paste your Epic Games library data.'
        
        if error is None:
            # Parse the manifest
            games = parse_epic_manifest(manifest_text)
            
            if not games:
                error = 'Could not parse Epic Games library data. Please check the format and try again.'
            else:
                db = get_db()
                imported_count = 0
                updated_count = 0
                
                for game_data in games:
                    game_name = game_data.get('name')
                    offer_id = game_data.get('offer_id') or game_data.get('app_id')
                    appid = offer_id if offer_id else f"epic-{game_name.lower().replace(' ', '-').replace(':', '').replace('/', '-')}"
                    
                    # Try to get game image
                    img_url = ''
                    if offer_id:
                        game_details = get_epic_game_details(offer_id)
                        if game_details and 'keyImages' in game_details:
                            for img in game_details['keyImages']:
                                if img.get('type') == 'OfferImageWide':
                                    img_url = img.get('url', '')
                                    break
                    
                    # Insert or update game
                    try:
                        db.execute(
                            'INSERT INTO game (appid, name, platform, playtime_forever, img_icon_url, img_logo_url)'
                            ' VALUES (?, ?, ?, ?, ?, ?)',
                            (appid, game_name, 'epic', 0, '', img_url)
                        )
                        imported_count += 1
                    except db.IntegrityError:
                        db.execute(
                            'UPDATE game SET name = ?, img_logo_url = ? WHERE appid = ? AND platform = ?',
                            (game_name, img_url, appid, 'epic')
                        )
                        updated_count += 1
                    
                    # Get game ID
                    game = db.execute(
                        'SELECT id FROM game WHERE appid = ? AND platform = ?', (appid, 'epic')
                    ).fetchone()
                    
                    if game:
                        try:
                            db.execute(
                                'INSERT INTO user_game_library (user_id, game_id, playtime_forever)'
                                ' VALUES (?, ?, ?)',
                                (g.user['id'], game['id'], 0)
                            )
                        except db.IntegrityError:
                            db.execute(
                                'UPDATE user_game_library SET imported_at = CURRENT_TIMESTAMP'
                                ' WHERE user_id = ? AND game_id = ?',
                                (g.user['id'], game['id'])
                            )
                
                db.commit()
                flash(f'Successfully imported {imported_count} new games and updated {updated_count} existing games!')
                return redirect(url_for('steam.library'))
        
        if error:
            flash(error)
    
    return render_template('epic/manifest_import.html')


@bp.route('/import', methods=('GET', 'POST'))
@login_required
def import_library():
    """Import user's Epic Games library using Ecom API or manual entry."""
    if request.method == 'POST':
        account_id = request.form.get('account_id', '').strip()
        manual_games = request.form.get('manual_games', '').strip()
        use_api = request.form.get('use_api') == 'true'
        error = None
        
        # Try API import if account_id provided
        if use_api and account_id:
            # Get access token
            access_token, token_error = get_epic_access_token()
            if token_error:
                error = token_error
            else:
                # Fetch library from Epic Games Ecom API
                games, fetch_error = fetch_epic_library(account_id, access_token)
                if fetch_error:
                    error = fetch_error
                elif games is None:
                    error = 'Failed to fetch Epic Games library.'
                elif len(games) == 0:
                    error = 'No games found in your Epic Games library.'
                
                if error is None:
                    db = get_db()
                    imported_count = 0
                    updated_count = 0
                    
                    for game_data in games:
                        offer_id = game_data.get('offer_id')
                        game_name = game_data.get('name', 'Unknown Game')
                        appid = offer_id or f"epic-{game_data.get('id', 'unknown')}"
                        
                        # Try to get game image from catalog
                        img_url = ''
                        if offer_id:
                            game_details = get_epic_game_details(offer_id)
                            if game_details and 'keyImages' in game_details:
                                for img in game_details['keyImages']:
                                    if img.get('type') == 'OfferImageWide':
                                        img_url = img.get('url', '')
                                        break
                        
                        # Insert or update game
                        try:
                            db.execute(
                                'INSERT INTO game (appid, name, platform, playtime_forever, img_icon_url, img_logo_url)'
                                ' VALUES (?, ?, ?, ?, ?, ?)',
                                (appid, game_name, 'epic', 0, '', img_url)
                            )
                            imported_count += 1
                        except db.IntegrityError:
                            # Game already exists, update it
                            db.execute(
                                'UPDATE game SET name = ?, img_logo_url = ? WHERE appid = ? AND platform = ?',
                                (game_name, img_url, appid, 'epic')
                            )
                            updated_count += 1
                        
                        # Get game ID
                        game = db.execute(
                            'SELECT id FROM game WHERE appid = ? AND platform = ?', (appid, 'epic')
                        ).fetchone()
                        
                        if game:
                            # Insert or update user_game_library
                            try:
                                db.execute(
                                    'INSERT INTO user_game_library (user_id, game_id, playtime_forever)'
                                    ' VALUES (?, ?, ?)',
                                    (g.user['id'], game['id'], 0)
                                )
                            except db.IntegrityError:
                                # Already in library, update
                                db.execute(
                                    'UPDATE user_game_library SET imported_at = CURRENT_TIMESTAMP'
                                    ' WHERE user_id = ? AND game_id = ?',
                                    (g.user['id'], game['id'])
                                )
                    
                    db.commit()
                    flash(f'Successfully imported {imported_count} new games and updated {updated_count} existing games from Epic Games!')
                    return redirect(url_for('steam.library'))
        
        # Fall back to manual entry
        elif manual_games:
            db = get_db()
            imported_count = 0
            updated_count = 0
            
            for line in manual_games.split('\n'):
                line = line.strip()
                if not line:
                    continue
                
                # Parse format: "Game Name|offer-id" or just "Game Name"
                parts = line.split('|')
                game_name = parts[0].strip()
                offer_id = parts[1].strip() if len(parts) > 1 else None
                
                if game_name:
                    # Create unique appid
                    appid = offer_id if offer_id else f"epic-{game_name.lower().replace(' ', '-').replace(':', '').replace('/', '-')}"
                    
                    # Try to get game image from Epic Games catalog
                    img_url = ''
                    if offer_id:
                        game_details = get_epic_game_details(offer_id)
                        if game_details and 'keyImages' in game_details:
                            for img in game_details['keyImages']:
                                if img.get('type') == 'OfferImageWide':
                                    img_url = img.get('url', '')
                                    break
                    
                    # Insert or update game
                    try:
                        db.execute(
                            'INSERT INTO game (appid, name, platform, playtime_forever, img_icon_url, img_logo_url)'
                            ' VALUES (?, ?, ?, ?, ?, ?)',
                            (appid, game_name, 'epic', 0, '', img_url)
                        )
                        imported_count += 1
                    except db.IntegrityError:
                        # Game already exists, update it
                        db.execute(
                            'UPDATE game SET name = ?, img_logo_url = ? WHERE appid = ? AND platform = ?',
                            (game_name, img_url, appid, 'epic')
                        )
                        updated_count += 1
                    
                    # Get game ID
                    game = db.execute(
                        'SELECT id FROM game WHERE appid = ? AND platform = ?', (appid, 'epic')
                    ).fetchone()
                    
                    if game:
                        # Insert or update user_game_library
                        try:
                            db.execute(
                                'INSERT INTO user_game_library (user_id, game_id, playtime_forever)'
                                ' VALUES (?, ?, ?)',
                                (g.user['id'], game['id'], 0)
                            )
                        except db.IntegrityError:
                            # Already in library, update
                            db.execute(
                                'UPDATE user_game_library SET imported_at = CURRENT_TIMESTAMP'
                                ' WHERE user_id = ? AND game_id = ?',
                                (g.user['id'], game['id'])
                            )
            
            db.commit()
            flash(f'Successfully imported {imported_count} new games and updated {updated_count} existing games!')
            return redirect(url_for('steam.library'))
        else:
            error = 'Please provide your Epic Games account ID for API import or enter games manually.'
        
        if error:
            flash(error)
    
    # Check if API credentials are configured
    credentials = get_epic_api_credentials()
    api_available = bool(credentials['client_id'] and credentials['client_secret'])
    
    return render_template('epic/import.html', api_available=api_available)


@bp.route('/import/manual', methods=('GET', 'POST'))
@login_required
def manual_import():
    """Manual Epic Games library import."""
    if request.method == 'POST':
        manual_games = request.form.get('manual_games', '').strip()
        error = None
        
        if not manual_games:
            error = 'Please enter at least one game.'
        
        if error is None:
            db = get_db()
            imported_count = 0
            updated_count = 0
            
            for line in manual_games.split('\n'):
                line = line.strip()
                if not line:
                    continue
                
                # Parse format: "Game Name|offer-id" or just "Game Name"
                parts = line.split('|')
                game_name = parts[0].strip()
                offer_id = parts[1].strip() if len(parts) > 1 else None
                
                if game_name:
                    # Create unique appid
                    appid = offer_id if offer_id else f"epic-{game_name.lower().replace(' ', '-').replace(':', '')}"
                    
                    # Try to get game image from Epic Games catalog
                    img_url = ''
                    if offer_id:
                        game_details = get_epic_game_details(offer_id)
                        if game_details and 'keyImages' in game_details:
                            for img in game_details['keyImages']:
                                if img.get('type') == 'OfferImageWide':
                                    img_url = img.get('url', '')
                                    break
                    
                    # Insert or update game
                    try:
                        db.execute(
                            'INSERT INTO game (appid, name, platform, playtime_forever, img_icon_url, img_logo_url)'
                            ' VALUES (?, ?, ?, ?, ?, ?)',
                            (appid, game_name, 'epic', 0, '', img_url)
                        )
                        imported_count += 1
                    except db.IntegrityError:
                        # Game already exists, update it
                        db.execute(
                            'UPDATE game SET name = ?, img_logo_url = ? WHERE appid = ? AND platform = ?',
                            (game_name, img_url, appid, 'epic')
                        )
                        updated_count += 1
                    
                    # Get game ID
                    game = db.execute(
                        'SELECT id FROM game WHERE appid = ? AND platform = ?', (appid, 'epic')
                    ).fetchone()
                    
                    if game:
                        # Insert or update user_game_library
                        try:
                            db.execute(
                                'INSERT INTO user_game_library (user_id, game_id, playtime_forever)'
                                ' VALUES (?, ?, ?)',
                                (g.user['id'], game['id'], 0)
                            )
                        except db.IntegrityError:
                            # Already in library, update
                            db.execute(
                                'UPDATE user_game_library SET imported_at = CURRENT_TIMESTAMP'
                                ' WHERE user_id = ? AND game_id = ?',
                                (g.user['id'], game['id'])
                            )
            
            db.commit()
            flash(f'Successfully imported {imported_count} new games and updated {updated_count} existing games!')
            return redirect(url_for('steam.library'))
        
        flash(error)
    
    return render_template('epic/manual_import.html')

