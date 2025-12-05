from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for
)

from flaskr.auth import login_required
from flaskr.db import get_db

bp = Blueprint('recommendations', __name__, url_prefix='/recommendations')


# Common game tags/genres
POPULAR_TAGS = [
    'Action', 'Adventure', 'RPG', 'Strategy', 'Simulation', 'Sports',
    'Racing', 'Puzzle', 'Indie', 'Casual', 'Multiplayer', 'Singleplayer',
    'FPS', 'Horror', 'Sci-Fi', 'Fantasy', 'Open World', 'Story Rich',
    'Co-op', 'Competitive', 'Sandbox', 'Survival', 'Crafting', 'Building'
]


@bp.route('/')
@login_required
def index():
    """Show game recommendations based on user preferences."""
    db = get_db()
    
    # Get user's preferred tags (handle case where table doesn't exist yet)
    try:
        user_tags = {row['tag']: row['weight'] for row in db.execute(
            'SELECT tag, weight FROM user_preferences WHERE user_id = ?',
            (g.user['id'],)
        ).fetchall()}
    except db.OperationalError:
        # Table doesn't exist yet, initialize empty
        user_tags = {}
    
    # Get user's current library game IDs
    user_game_ids = {row['game_id'] for row in db.execute(
        'SELECT game_id FROM user_game_library WHERE user_id = ?',
        (g.user['id'],)
    ).fetchall()}
    
    # Get games from followed users
    followed_user_games = {}
    if user_tags:
        followed_users = db.execute(
            'SELECT following_id FROM user_follows WHERE follower_id = ?',
            (g.user['id'],)
        ).fetchall()
        
        for followed in followed_users:
            games = db.execute(
                'SELECT g.id, g.name, g.appid, g.img_logo_url, ugl.playtime_forever'
                ' FROM user_game_library ugl'
                ' JOIN game g ON ugl.game_id = g.id'
                ' WHERE ugl.user_id = ? AND g.id NOT IN ({})'.format(
                    ','.join('?' * len(user_game_ids)) if user_game_ids else '0'
                ),
                (followed['following_id'],) + tuple(user_game_ids) if user_game_ids else (followed['following_id'],)
            ).fetchall()
            
            for game in games:
                if game['id'] not in followed_user_games:
                    followed_user_games[game['id']] = {
                        'game': game,
                        'recommendation_score': 0,
                        'reason': 'Played by followed users'
                    }
    
    # Get games with matching tags
    tag_based_games = {}
    if user_tags:
        try:
            for tag, weight in user_tags.items():
                games = db.execute(
                    'SELECT g.id, g.name, g.appid, g.img_logo_url'
                    ' FROM game g'
                    ' JOIN game_tag gt ON g.id = gt.game_id'
                    ' WHERE gt.tag = ? AND g.id NOT IN ({})'.format(
                        ','.join('?' * len(user_game_ids)) if user_game_ids else '0'
                    ),
                    (tag,) + tuple(user_game_ids) if user_game_ids else (tag,)
                ).fetchall()
            
                for game in games:
                    if game['id'] not in tag_based_games:
                        tag_based_games[game['id']] = {
                            'game': game,
                            'recommendation_score': 0,
                            'matching_tags': []
                        }
                    tag_based_games[game['id']]['recommendation_score'] += weight
                    tag_based_games[game['id']]['matching_tags'].append(tag)
        except db.OperationalError:
            # game_tag table doesn't exist yet
            pass
    
    # Combine recommendations
    recommendations = {}
    
    # Add tag-based recommendations
    for game_id, data in tag_based_games.items():
        recommendations[game_id] = {
            'game': data['game'],
            'score': data['recommendation_score'],
            'reason': f"Matches your tags: {', '.join(data['matching_tags'][:3])}"
        }
    
    # Add followed user games (boost their score)
    for game_id, data in followed_user_games.items():
        if game_id in recommendations:
            recommendations[game_id]['score'] += 5  # Boost for being played by friends
            if 'friends' not in recommendations[game_id]['reason'].lower():
                recommendations[game_id]['reason'] += '; Also played by followed users'
        else:
            recommendations[game_id] = {
                'game': data['game'],
                'score': 5,
                'reason': data['reason']
            }
    
    # Sort by recommendation score
    sorted_recommendations = sorted(
        recommendations.values(),
        key=lambda x: x['score'],
        reverse=True
    )
    
    return render_template(
        'recommendations/index.html',
        recommendations=sorted_recommendations[:50],  # Top 50
        has_preferences=bool(user_tags)
    )


@bp.route('/preferences', methods=('GET', 'POST'))
@login_required
def preferences():
    """Manage user tag preferences."""
    db = get_db()
    
    if request.method == 'POST':
        # Get selected tags from form
        selected_tags = request.form.getlist('tags')
        
        try:
            # Clear existing preferences
            db.execute('DELETE FROM user_preferences WHERE user_id = ?', (g.user['id'],))
            
            # Add new preferences
            for tag in selected_tags:
                if tag in POPULAR_TAGS:
                    db.execute(
                        'INSERT INTO user_preferences (user_id, tag, weight) VALUES (?, ?, ?)',
                        (g.user['id'], tag, 1.0)
                    )
            
            db.commit()
            flash('Preferences updated successfully!')
            return redirect(url_for('recommendations.index'))
        except db.OperationalError:
            flash('Database tables not initialized. Please run: flask --app flaskr init-db')
            return redirect(url_for('recommendations.index'))
    
    # Get current preferences
    try:
        current_tags = {row['tag'] for row in db.execute(
            'SELECT tag FROM user_preferences WHERE user_id = ?',
            (g.user['id'],)
        ).fetchall()}
    except db.OperationalError:
        current_tags = set()
    
    return render_template(
        'recommendations/preferences.html',
        all_tags=POPULAR_TAGS,
        current_tags=current_tags
    )


@bp.route('/game/<int:game_id>/tags', methods=('GET', 'POST'))
@login_required
def manage_game_tags(game_id):
    """Add or remove tags for a specific game."""
    db = get_db()
    
    game = db.execute('SELECT * FROM game WHERE id = ?', (game_id,)).fetchone()
    if not game:
        flash('Game not found.')
        return redirect(url_for('recommendations.index'))
    
    if request.method == 'POST':
        try:
            selected_tags = request.form.getlist('tags')
            
            # Remove all existing tags for this game
            db.execute('DELETE FROM game_tag WHERE game_id = ?', (game_id,))
            
            # Add new tags
            for tag in selected_tags:
                if tag in POPULAR_TAGS:
                    try:
                        db.execute(
                            'INSERT INTO game_tag (game_id, tag) VALUES (?, ?)',
                            (game_id, tag)
                        )
                    except db.IntegrityError:
                        pass  # Tag already exists
            
            db.commit()
            flash(f'Tags updated for {game["name"]}!')
            return redirect(url_for('steam.library'))
        except db.OperationalError:
            flash('Database tables not initialized. Please run: flask --app flaskr init-db')
            return redirect(url_for('steam.library'))
    
    # Get current tags for this game
    try:
        current_tags = {row['tag'] for row in db.execute(
            'SELECT tag FROM game_tag WHERE game_id = ?',
            (game_id,)
        ).fetchall()}
    except db.OperationalError:
        current_tags = set()
    
    return render_template(
        'recommendations/game_tags.html',
        game=game,
        all_tags=POPULAR_TAGS,
        current_tags=current_tags
    )

