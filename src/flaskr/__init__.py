import os

from flask import Flask


def create_app(test_config=None):
    # create and configure the app
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY='dev',
        DATABASE=os.path.join(app.instance_path, 'flaskr.sqlite'),
    )

    if test_config is None:
        # load the instance config, if it exists, when not testing
        app.config.from_pyfile('config.py', silent=True)
    else:
        # load the test config if passed in
        app.config.from_mapping(test_config)

    # ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    # a simple page that says hello
    @app.route('/hello')
    def hello():
        return 'Hello, World!'

    from . import db
    db.init_app(app)

    from . import auth
    app.register_blueprint(auth.bp)

    from . import steam
    app.register_blueprint(steam.bp)
    
    from . import social
    app.register_blueprint(social.bp)
    
    from . import recommendations
    app.register_blueprint(recommendations.bp)
    
    # Set root route to library (or login if not authenticated)
    @app.route('/')
    def index():
        from flask import redirect, url_for, session
        if session.get('user_id'):
            return redirect(url_for('steam.library'))
        return redirect(url_for('auth.login'))

    return app