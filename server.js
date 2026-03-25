const express = require('express');
const path = require('path');
const session = require('express-session');


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

// Serve ALL static files from 'root'. 
// Because the files are in `root/parrot/`, visiting `http://localhost:3000/parrot/` works automatically via this single command!
app.use(express.static(path.join(__dirname, 'root')));

// SPA Fallback for UserLooker React application
app.get(/^\/userlooker(?:\/.*)?$/, (req, res) => {
    res.sendFile(path.join(__dirname, 'root', 'userlooker', 'index.html'));
});

// Import the modular API logic for the Parrot System
const parrotRouter = require('./website_sys/parrot_system/router');

// Mount the parrot router under the /api/parrot namespace
app.use('/api', parrotRouter);

// Set up http-proxy-middleware for the standalone Python backend
const { createProxyMiddleware } = require('http-proxy-middleware');
app.use('/api/userlooker', createProxyMiddleware({
    target: 'http://127.0.0.1:8001',
    changeOrigin: true,
    pathRewrite: {
        '^/api/userlooker': '', // Re-route to bare Python endpoints
    },
}));

app.listen(PORT, () => {
    console.log(`Server successfully started! \nOpen your browser and navigate to: http://localhost:${PORT}`);
});
