DROP TABLE IF EXISTS user;
DROP TABLE IF EXISTS post;
DROP TABLE IF EXISTS user_game_library;
DROP TABLE IF EXISTS user_follows;
DROP TABLE IF EXISTS game;

CREATE TABLE user (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      username TEXT UNIQUE NOT NULL,
                      password TEXT NOT NULL
);

CREATE TABLE post (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      author_id INTEGER NOT NULL,
                      created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      title TEXT NOT NULL,
                      body TEXT NOT NULL,
                      FOREIGN KEY (author_id) REFERENCES user (id)
);

CREATE TABLE game (
                      id INTEGER PRIMARY KEY,
                      name TEXT NOT NULL,
                      appid TEXT UNIQUE NOT NULL,
                      platform TEXT NOT NULL DEFAULT 'steam',
                      playtime_forever INTEGER DEFAULT 0,
                      img_icon_url TEXT,
                      img_logo_url TEXT,
                      created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE user_game_library (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER NOT NULL,
                      game_id INTEGER NOT NULL,
                      playtime_forever INTEGER DEFAULT 0,
                      imported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      FOREIGN KEY (user_id) REFERENCES user (id),
                      FOREIGN KEY (game_id) REFERENCES game (id),
                      UNIQUE(user_id, game_id)
);

CREATE TABLE user_follows (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      follower_id INTEGER NOT NULL,
                      following_id INTEGER NOT NULL,
                      created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      FOREIGN KEY (follower_id) REFERENCES user (id),
                      FOREIGN KEY (following_id) REFERENCES user (id),
                      UNIQUE(follower_id, following_id),
                      CHECK(follower_id != following_id)
);
