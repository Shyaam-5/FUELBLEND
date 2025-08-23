// static/js/main.js
document.addEventListener('DOMContentLoaded', function() {
    // File upload handling
    const fileInput = document.getElementById('fileInput');
    const uploadArea = document.getElementById('uploadArea');
    const fileInfo = document.getElementById('fileInfo');
    const fileName = document.getElementById('fileName');
    const predictBtn = document.getElementById('predictBtn');

    if (fileInput && uploadArea) {
        // File input change event
        fileInput.addEventListener('change', handleFileSelect);

        // Drag and drop events
        uploadArea.addEventListener('dragover', handleDragOver);
        uploadArea.addEventListener('dragleave', handleDragLeave);
        uploadArea.addEventListener('drop', handleFileDrop);
        uploadArea.addEventListener('click', () => fileInput.click());
    }

    function handleFileSelect(e) {
        const file = e.target.files[0];
        if (file) {
            displayFileInfo(file);
        }
    }

    function handleDragOver(e) {
        e.preventDefault();
        uploadArea.classList.add('dragover');
    }

    function handleDragLeave(e) {
        e.preventDefault();
        uploadArea.classList.remove('dragover');
    }

    function handleFileDrop(e) {
        e.preventDefault();
        uploadArea.classList.remove('dragover');
        
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            const file = files[0];
            if (file.type === 'text/csv' || file.name.endsWith('.csv')) {
                fileInput.files = files;
                displayFileInfo(file);
            } else {
                alert('Please select a CSV file.');
            }
        }
    }

    function displayFileInfo(file) {
        fileName.textContent = file.name;
        fileInfo.style.display = 'block';
        predictBtn.disabled = false;
    }

    // Clear file function
    window.clearFile = function() {
        fileInput.value = '';
        fileInfo.style.display = 'none';
        predictBtn.disabled = true;
    };

    // Download CSV function for results page
    window.downloadCSV = function() {
        const table = document.getElementById('resultsTable');
        if (table) {
            let csv = [];
            const rows = table.querySelectorAll('tr');
            
            for (let i = 0; i < rows.length; i++) {
                const row = [], cols = rows[i].querySelectorAll('td, th');
                
                for (let j = 0; j < cols.length; j++) {
                    let data = cols[j].innerText.replace(/(\r\n|\n|\r)/gm, '').replace(/(\s\s)/gm, ' ');
                    data = data.replace(/"/g, '""');
                    row.push('"' + data + '"');
                }
                csv.push(row.join(','));
            }
            
            const csvFile = new Blob([csv.join('\n')], { type: 'text/csv' });
            const downloadLink = document.createElement('a');
            downloadLink.download = 'prediction_results.csv';
            downloadLink.href = window.URL.createObjectURL(csvFile);
            downloadLink.style.display = 'none';
            document.body.appendChild(downloadLink);
            downloadLink.click();
            document.body.removeChild(downloadLink);
        }
    };

    // Form submission with loading state
    const uploadForm = document.getElementById('uploadForm');
    if (uploadForm) {
        uploadForm.addEventListener('submit', function(e) {
            const submitBtn = predictBtn;
            submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Processing...';
            submitBtn.disabled = true;
        });
    }

    // Add fade-in animation to elements
    const animatedElements = document.querySelectorAll('.feature-card, .upload-card, .results-table-container, .history-item');
    animatedElements.forEach(el => el.classList.add('fade-in'));
});

// Toast notifications (optional)
function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `alert alert-${type} alert-dismissible fade show position-fixed`;
    toast.style.top = '20px';
    toast.style.right = '20px';
    toast.style.zIndex = '9999';
    toast.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    
    document.body.appendChild(toast);
    
    setTimeout(() => {
        toast.remove();
    }, 5000);
}
