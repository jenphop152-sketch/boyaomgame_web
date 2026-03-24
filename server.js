const express = require('express');
const path = require('path');

const app = express();
const PORT = process.env.PORT || 3000;

// Serve static files from the 'root' directory where index.html is located
app.use(express.static(path.join(__dirname, 'root')));

// Explicitly send index.html when the root URL is requested
app.get('/', (req, res) => {
    res.sendFile(path.join(__dirname, 'root', 'index.html'));
});

// Start the server
app.listen(PORT, () => {
    console.log(`Server successfully started! \nOpen your browser and navigate to: http://localhost:${PORT}`);
});
