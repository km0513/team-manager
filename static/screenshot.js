// screenshot.js: Capture full-page screenshot, show preview, and upload to Flask backend
// Requires html2canvas via CDN

document.addEventListener('DOMContentLoaded', function() {
    // Add screenshot button if not present
    let btn = document.getElementById('screenshot-btn');
    if (!btn) {
        btn = document.createElement('button');
        btn.id = 'screenshot-btn';
        btn.innerText = 'Take Full Page Screenshot';
        btn.className = 'bg-upgradRed text-white px-4 py-2 rounded shadow mb-4';
        const container = document.querySelector('.max-w-2xl') || document.body;
        container.insertBefore(btn, container.firstChild);
    }
    // Add preview area
    let preview = document.getElementById('screenshot-preview');
    if (!preview) {
        preview = document.createElement('div');
        preview.id = 'screenshot-preview';
        preview.className = 'mb-4';
        btn.after(preview);
    }
    // Screenshot logic
    btn.onclick = function() {
        html2canvas(document.body, {
            useCORS: true,
            windowWidth: document.body.scrollWidth,
            windowHeight: document.body.scrollHeight
        }).then(function(canvas) {
            // Show thumbnail
            const img = document.createElement('img');
            img.src = canvas.toDataURL('image/png');
            img.style.maxWidth = '200px';
            img.style.cursor = 'pointer';
            img.title = 'Click to view full screenshot';
            img.onclick = function() {
                const win = window.open();
                win.document.write('<img src="' + img.src + '" style="max-width:100%">');
            };
            preview.innerHTML = '';
            preview.appendChild(img);
            // Upload to backend
            fetch('/upload_screenshot', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ image: img.src })
            })
            .then(res => res.json())
            .then(data => {
                if (data.image_url) {
                    // Optionally show a link to the saved image
                    let link = document.createElement('a');
                    link.href = data.image_url;
                    link.innerText = 'View Saved Screenshot';
                    link.target = '_blank';
                    link.className = 'ml-4 text-upgradRed underline';
                    preview.appendChild(document.createElement('br'));
                    preview.appendChild(link);
                }
            });
        });
    };
});
