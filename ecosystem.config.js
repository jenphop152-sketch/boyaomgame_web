module.exports = {
  apps: [
    {
      name: "MainNodeServer",
      script: "server.js",
      cwd: ".",
      env: {
        NODE_ENV: "production",
      }
    },
    {
      name: "UserLookerPythonAPI",
      script: "python",
      args: "-m uvicorn main:app --port 8001",
      cwd: "./website_sys/userlooker_sys",
    }
  ]
};
