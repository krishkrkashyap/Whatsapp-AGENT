// Check message handling in OpenWA
const fs = require('fs');
const content = fs.readFileSync('/app/dist/plugins/engines/whatsapp-web-js/index.js', 'utf8');
// Find .on('message' calls
const lines = content.split('\n');
let found = false;
for (let i = 0; i < lines.length; i++) {
    if (lines[i].includes('.on(') && (lines[i].includes('message') || lines[i].includes('ready') || lines[i].includes('disconnected'))) {
        if (!found) console.log('--- Relevant event handlers ---');
        found = true;
        // Print this line and next few
        console.log(`Line ${i + 1}: ${lines[i].substring(0, 150)}`);
        for (let j = i + 1; j < Math.min(i + 5, lines.length); j++) {
            console.log(`  ${j + 1}: ${lines[j].substring(0, 150)}`);
        }
    }
}
