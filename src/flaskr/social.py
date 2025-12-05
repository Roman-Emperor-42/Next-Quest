from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for
)

from flaskr.auth import login_required
from flaskr.db import get_db

bp = Blueprint('social', __name__, url_prefix='/social')


@bp.route('/users')
@login_required
def users():
    """Browse all users on the site."""
    db = get_db()
    search_query = request.args.get('search', '').strip()
    
    # Get users (excluding current user)
    if search_query:
        users = db.execute(
            'SELECT id, username FROM user WHERE username LIKE ? AND id != ? ORDER BY username',
            (f'%{search_query}%', g.user['id'])
        ).fetchall()
    else:
        users = db.execute(
            'SELECT id, username FROM user WHERE id != ? ORDER BY username',
            (g.user['id'],)
        ).fetchall()
    
    # Get list of users current user is following
    following_ids = {row['following_id'] for row in db.execute(
        'SELECT following_id FROM user_follows WHERE follower_id = ?',
        (g.user['id'],)
    ).fetchall()}
    
    return render_template('social/users.html', users=users, following_ids=following_ids, search_query=search_query)


@bp.route('/users/<int:user_id>/follow', methods=('POST',))
@login_required
def follow_user(user_id):
    """Follow another user."""
    db = get_db()
    
    # Check if user exists
    user = db.execute('SELECT id, username FROM user WHERE id = ?', (user_id,)).fetchone()
    if not user:
        flash('User not found.')
        return redirect(url_for('social.users'))
    
    # Can't follow yourself
    if user_id == g.user['id']:
        flash('You cannot follow yourself.')
        return redirect(url_for('social.users'))
    
    # Check if already following
    existing = db.execute(
        'SELECT id FROM user_follows WHERE follower_id = ? AND following_id = ?',
        (g.user['id'], user_id)
    ).fetchone()
    
    if existing:
        flash(f'You are already following {user["username"]}.')
    else:
        db.execute(
            'INSERT INTO user_follows (follower_id, following_id) VALUES (?, ?)',
            (g.user['id'], user_id)
        )
        db.commit()
        flash(f'You are now following {user["username"]}!')
    
    return redirect(url_for('social.users'))


@bp.route('/users/<int:user_id>/unfollow', methods=('POST',))
@login_required
def unfollow_user(user_id):
    """Unfollow a user."""
    db = get_db()
    
    user = db.execute('SELECT username FROM user WHERE id = ?', (user_id,)).fetchone()
    if user:
        db.execute(
            'DELETE FROM user_follows WHERE follower_id = ? AND following_id = ?',
            (g.user['id'], user_id)
        )
        db.commit()
        flash(f'You have unfollowed {user["username"]}.')
    
    return redirect(request.referrer or url_for('social.users'))


@bp.route('/following')
@login_required
def following():
    """View users you are following."""
    db = get_db()
    
    following = db.execute(
        'SELECT u.id, u.username, uf.created_at'
        ' FROM user_follows uf'
        ' JOIN user u ON uf.following_id = u.id'
        ' WHERE uf.follower_id = ?'
        ' ORDER BY uf.created_at DESC',
        (g.user['id'],)
    ).fetchall()
    
    return render_template('social/following.html', following=following)


@bp.route('/common-games/<int:user_id>')
@login_required
def common_games(user_id):
    """View games in common with another user."""
    db = get_db()
    
    # Get user info
    other_user = db.execute('SELECT id, username FROM user WHERE id = ?', (user_id,)).fetchone()
    if not other_user:
        flash('User not found.')
        return redirect(url_for('social.users'))
    
    # Check if following
    is_following = db.execute(
        'SELECT id FROM user_follows WHERE follower_id = ? AND following_id = ?',
        (g.user['id'], user_id)
    ).fetchone() is not None
    
    # Get sort parameters (default to relevance)
    sort_by = request.args.get('sort', 'relevance')
    sort_order = request.args.get('order', 'desc')
    
    valid_sorts = {
        'name': 'name',
        'playtime': 'playtime',
        'my_playtime': 'my_playtime',
        'their_playtime': 'their_playtime',
        'relevance': 'relevance'
    }
    valid_orders = ['asc', 'desc']
    
    if sort_by not in valid_sorts:
        sort_by = 'name'
    if sort_order not in valid_orders:
        sort_order = 'asc'
    
    order_column = valid_sorts[sort_by]
    order_direction = sort_order.upper()
    
    # Get common games with playtime
    # Calculate relevance score: geometric mean of playtimes * log of total playtime
    # This favors games where both users have significant playtime
    common_games_raw = db.execute(
        'SELECT g.id, g.appid, g.name, g.img_logo_url,'
        ' my_lib.playtime_forever as my_playtime,'
        ' their_lib.playtime_forever as their_playtime,'
        ' (my_lib.playtime_forever + their_lib.playtime_forever) as total_playtime'
        ' FROM game g'
        ' INNER JOIN user_game_library my_lib ON g.id = my_lib.game_id AND my_lib.user_id = ?'
        ' INNER JOIN user_game_library their_lib ON g.id = their_lib.game_id AND their_lib.user_id = ?',
        (g.user['id'], user_id)
    ).fetchall()
    
    # Calculate relevance score for each game
    import math
    common_games = []
    for game in common_games_raw:
        my_playtime = game['my_playtime'] or 0
        their_playtime = game['their_playtime'] or 0
        total_playtime = game['total_playtime'] or 0
        
        # Relevance = geometric mean (balanced playtime) * log(total + 1)
        # This favors games where both users have significant playtime
        # while still rewarding higher total playtime
        if my_playtime > 0 and their_playtime > 0:
            geometric_mean = math.sqrt(my_playtime * their_playtime)
            relevance = geometric_mean * math.log(total_playtime + 1)
        else:
            relevance = 0
        
        # Create a dict with all fields plus relevance
        game_dict = dict(game)
        game_dict['relevance'] = relevance
        common_games.append(game_dict)
    
    # Sort by the selected column
    if sort_by == 'relevance':
        common_games.sort(key=lambda x: x['relevance'], reverse=(sort_order == 'desc'))
    elif sort_by == 'name':
        common_games.sort(key=lambda x: x['name'].lower(), reverse=(sort_order == 'desc'))
    elif sort_by == 'playtime':
        common_games.sort(key=lambda x: x['total_playtime'], reverse=(sort_order == 'desc'))
    elif sort_by == 'my_playtime':
        common_games.sort(key=lambda x: x['my_playtime'], reverse=(sort_order == 'desc'))
    elif sort_by == 'their_playtime':
        common_games.sort(key=lambda x: x['their_playtime'], reverse=(sort_order == 'desc'))
    
    return render_template(
        'social/common_games.html',
        other_user=other_user,
        common_games=common_games,
        is_following=is_following,
        sort_by=sort_by,
        sort_order=sort_order
    )

