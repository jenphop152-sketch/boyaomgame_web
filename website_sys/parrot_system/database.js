const sqlite3 = require('sqlite3').verbose();
const path = require('path');

// Create or open the SQLite database
const dbPath = path.resolve(__dirname, 'database.sqlite');
const db = new sqlite3.Database(dbPath, (err) => {
    if (err) {
        console.error("Error opening database: " + err.message);
    } else {
        console.log("Connected to the SQLite database.");
        
        // Create the 'posts' table if it doesn't exist
        db.run(`CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            date TEXT NOT NULL,
            summary TEXT NOT NULL,
            content TEXT NOT NULL
        )`);

        // Create the 'users' table if it doesn't exist
        db.run(`CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )`, (err) => {
            if (!err) {
                // Prevent duplicate default admin insertion by checking row count
                db.get("SELECT count(*) as count FROM users", (err, row) => {
                    if (row && row.count === 0) {
                        db.run("INSERT INTO users (username, password) VALUES ('admin', 'password')");
                    }
                });
            }
        });
    }
});

module.exports = db;
