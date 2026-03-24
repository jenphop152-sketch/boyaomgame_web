const express = require('express');
const path = require('path');
const session = require('express-session');
const db = require('./database');

const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(session({
    secret: 'parrot-secret-key-12345',
    resave: false,
    saveUninitialized: false,
    cookie: { secure: false, maxAge: 1000 * 60 * 60 * 24 } // 24 hours
}));

// Serve ALL static files from 'root'. Since index.html inside root exists, accessing '/' will serve root/index.html.
app.use(express.static(path.join(__dirname, 'root')));

// API Endpoint to handle admin login
app.post('/api/login', (req, res) => {
    const { username, password } = req.body;
    // Hardcoded credentials for simplicity
    if (username === 'admin' && password === 'password') {
        req.session.isAdmin = true;
        res.json({ success: true, message: 'Logged in successfully' });
    } else {
        res.status(401).json({ success: false, message: 'Invalid credentials' });
    }
});

// API Endpoint to check auth status
app.get('/api/check-auth', (req, res) => {
    if (req.session.isAdmin) {
        res.json({ authenticated: true });
    } else {
        res.json({ authenticated: false });
    }
});

// API Endpoint to logout
app.post('/api/logout', (req, res) => {
    req.session.destroy();
    res.json({ success: true });
});

// Middleware to protect admin routes
function requireAdmin(req, res, next) {
    if (req.session.isAdmin) {
        next();
    } else {
        res.status(401).json({ success: false, message: 'Unauthorized' });
    }
}

// API Endpoint to GET all posts
app.get('/api/posts', (req, res) => {
    db.all("SELECT id, title, date, summary FROM posts ORDER BY id DESC", [], (err, rows) => {
        if (err) {
            res.status(500).json({ error: err.message });
        } else {
            res.json({ posts: rows });
        }
    });
});

// API Endpoint to GET a single post by ID
app.get('/api/posts/:id', (req, res) => {
    const id = req.params.id;
    db.get("SELECT * FROM posts WHERE id = ?", [id], (err, row) => {
        if (err) {
            res.status(500).json({ error: err.message });
        } else if (row) {
            res.json({ post: row });
        } else {
            res.status(404).json({ error: "Post not found" });
        }
    });
});

// API Endpoint to POST a new post (Protected)
app.post('/api/posts', requireAdmin, (req, res) => {
    const { title, date, summary, content } = req.body;
    if (!title || !date || !summary || !content) {
        return res.status(400).json({ error: "All fields are required" });
    }

    db.run(
        `INSERT INTO posts (title, date, summary, content) VALUES (?, ?, ?, ?)`,
        [title, date, summary, content],
        function (err) {
            if (err) {
                res.status(500).json({ error: err.message });
            } else {
                res.json({ success: true, postId: this.lastID });
            }
        }
    );
});


// API Endpoint to run RAW SQL (Admin Only)
app.post('/api/sql', requireAdmin, (req, res) => {
    const { query } = req.body;
    if (!query) return res.status(400).json({ error: "No query provided" });
    
    // Determine if it's a read or write operation
    const q = query.trim().toUpperCase();
    if (q.startsWith('SELECT') || q.startsWith('PRAGMA')) {
        db.all(query, [], (err, rows) => {
            if (err) return res.status(500).json({ error: err.message });
            res.json({ success: true, type: 'select', data: rows });
        });
    } else {
        db.run(query, [], function(err) {
            if (err) return res.status(500).json({ error: err.message });
            res.json({ success: true, type: 'run', changes: this.changes, lastID: this.lastID });
        });
    }
});

app.listen(PORT, () => {
    console.log(`Server successfully started! \nOpen your browser and navigate to: http://localhost:${PORT}`);
});
