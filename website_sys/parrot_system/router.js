const express = require('express');
const router = express.Router();
const db = require('./database');

// Middleware to protect admin routes
function requireAdmin(req, res, next) {
    if (req.session.isAdmin) {
        next();
    } else {
        res.status(401).json({ success: false, message: 'Unauthorized' });
    }
}

// API Endpoint to handle// Admin login
router.post('/login', (req, res) => {
    const { username, password } = req.body;
    db.get("SELECT * FROM users WHERE username = ? AND password = ?", [username, password], (err, row) => {
        if (err) {
            res.status(500).json({ success: false, message: 'Server error' });
        } else if (row) {
            req.session.isAdmin = true;
            res.json({ success: true, message: 'Logged in successfully' });
        } else {
            res.status(401).json({ success: false, message: 'Invalid credentials' });
        }
    });
});

// API Endpoint to check auth status
router.get('/check-auth', (req, res) => {
    if (req.session.isAdmin) {
        res.json({ authenticated: true });
    } else {
        res.json({ authenticated: false });
    }
});

// API Endpoint to logout
router.post('/logout', (req, res) => {
    req.session.destroy();
    res.json({ success: true });
});

// API Endpoint to GET all posts
router.get('/posts', (req, res) => {
    db.all("SELECT id, title, date, summary FROM posts ORDER BY id DESC", [], (err, rows) => {
        if (err) {
            res.status(500).json({ error: err.message });
        } else {
            res.json({ posts: rows });
        }
    });
});

// API Endpoint to GET a single post by ID
router.get('/posts/:id', (req, res) => {
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
router.post('/posts', requireAdmin, (req, res) => {
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
router.post('/sql', requireAdmin, (req, res) => {
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

module.exports = router;
