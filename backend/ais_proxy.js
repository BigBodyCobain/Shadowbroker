const WebSocket = require('ws');

const args = process.argv.slice(2);
const API_KEY = args[0] || '75cc39af03c9cc23c90e8a7b3c3bc2b2a507c5fb';

const FILTER = [
    // US Aircraft Carriers and major naval groups
    { "MMSI": 338000000 }, { "MMSI": 338100000 }, // US Navy general prefixes
    // Plus let's grab some global shipping for density
    { "BoundingBoxes": [[[-90, -180], [90, 180]]] }
];

function connect() {
    const ws = new WebSocket('wss://stream.aisstream.io/v0/stream');

    ws.on('open', () => {
        const subMsg = {
            APIKey: API_KEY,
            BoundingBoxes: [
                [[-90, -180], [90, 180]]
            ],
            FilterMessageTypes: [
                "PositionReport",
                "ShipStaticData",
                "StandardClassBPositionReport"
            ]
        };
        ws.send(JSON.stringify(subMsg));
    });

    ws.on('message', (data) => {
        // Output raw AIS message JSON to stdout so Python can consume it
        // We ensure exactly one JSON object per line.
        try {
            const parsed = JSON.parse(data);
            console.log(JSON.stringify(parsed));
        } catch (e) {
            // ignore non-json
        }
    });

    ws.on('error', (err) => {
        console.error("WebSocket Proxy Error:", err.message);
    });

    ws.on('close', () => {
        console.error("WebSocket Proxy Closed. Reconnecting in 5s...");
        setTimeout(connect, 5000);
    });
}

connect();
