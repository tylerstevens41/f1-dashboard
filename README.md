# F1 Dashboard

Existing React/Vite dashboard with a backend-only LiveF1 bridge.

- [LIVE/TEST setup, Windows commands, protocol, verification limits and migration inventory](docs/livef1-milestone-1.md)
- [Reusable circuit architecture](docs/circuit-system.md)

```sh
npm ci
npm run dev
```

Backend (separate terminal):

```sh
python -m pip install -r bridge/requirements.txt
python -m bridge.server
```

For development archives use `--login --idle --allow-test`, following the verification guide. Never put F1 credentials in frontend variables or commits. LiveF1 1.3.0 is pinned. Authenticated historical retrieval and Austin alignment must be verified locally; compilation is not proof of GPS accuracy.

```sh
npm test
npm run build
npm run lint
python -m unittest discover -s bridge/tests -v
```

Legacy OpenF1 playback remains available only in development until the LiveF1 replacement is verified. No archive data or credentials are bundled.
