module.exports = {
  apps: [{
    name: 'wa',
    cwd: __dirname,
    script: 'main.py',
    interpreter: `${__dirname}/.venv312/bin/python`,
    autorestart: true,
    restart_delay: 5000,
    env: { PYTHONUNBUFFERED: '1' },
  }],
};
