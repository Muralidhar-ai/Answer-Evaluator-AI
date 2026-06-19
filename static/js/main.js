document.addEventListener('DOMContentLoaded', () => {
    // ----------------------------------------------------
    // 1. Setup Drag and Drop File Upload Areas
    // ----------------------------------------------------
    const setupDropzone = (zoneId, inputId, labelId) => {
        const dropzone = document.getElementById(zoneId);
        const input = document.getElementById(inputId);
        const label = document.getElementById(labelId);
        
        if (!dropzone || !input) return;

        // Click zone to open file browser
        dropzone.addEventListener('click', () => input.click());

        // Visual dragover highlights
        dropzone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropzone.classList.add('dragover');
        });

        dropzone.addEventListener('dragleave', () => {
            dropzone.classList.remove('dragover');
        });

        dropzone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropzone.classList.remove('dragover');
            
            if (e.dataTransfer.files.length > 0) {
                input.files = e.dataTransfer.files;
                updateFileName(input, label);
            }
        });

        input.addEventListener('change', () => {
            updateFileName(input, label);
        });
    };

    const updateFileName = (input, label) => {
        if (input.files && input.files.length > 0) {
            label.innerHTML = `<strong>Selected file:</strong> ${input.files[0].name}`;
        }
    };

    setupDropzone('qp-dropzone', 'qp-file', 'qp-file-label');
    setupDropzone('ak-dropzone', 'ak-file', 'ak-file-label');
    setupDropzone('student-dropzone', 'student-file', 'student-file-label');

    // ----------------------------------------------------
    // 2. AJAX Upload & Simulated Step Progress
    // ----------------------------------------------------
    const uploadForm = document.getElementById('upload-form');
    if (uploadForm) {
        uploadForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            // Form data
            const formData = new FormData(uploadForm);
            
            // Get files & inputs to validate
            const qpFile = document.getElementById('qp-file').files[0];
            const qpText = document.getElementById('qp-text').value.trim();
            const akFile = document.getElementById('ak-file').files[0];
            const akText = document.getElementById('ak-text').value.trim();
            const studentFile = document.getElementById('student-file').files[0];

            if (!qpFile && !qpText) {
                alert('Please upload a Question Paper file or paste its text.');
                return;
            }
            if (!akFile && !akText) {
                alert('Please upload an Answer Key file or paste its text.');
                return;
            }
            if (!studentFile) {
                alert("Please upload the Student's Answer Sheet.");
                return;
            }

            // Show Progress Modal
            const progressModal = new bootstrap.Modal(document.getElementById('progressModal'), {
                backdrop: 'static',
                keyboard: false
            });
            progressModal.show();

            // Set up simulated step indicators
            const steps = [
                { elementId: 'step-qp', name: 'Extracting Question Paper structure...' },
                { elementId: 'step-ak', name: 'Extracting Answer Key rubrics...' },
                { elementId: 'step-ocr', name: 'Performing OCR on handwritten Answer Sheet...' },
                { elementId: 'step-align', name: 'Aligning questions and answers...' }
            ];

            // Set all to pending initial state
            steps.forEach(s => setStepState(s.elementId, 'pending'));

            // Progress simulator variables
            let currentStepIdx = 0;
            setStepState(steps[currentStepIdx].elementId, 'loading');

            const stepTimer = setInterval(() => {
                if (currentStepIdx < steps.length - 1) {
                    setStepState(steps[currentStepIdx].elementId, 'done');
                    currentStepIdx++;
                    setStepState(steps[currentStepIdx].elementId, 'loading');
                }
            }, 3500); // Progress transitions every 3.5 seconds

            try {
                const response = await fetch('/upload-ajax', {
                    method: 'POST',
                    body: formData
                });
                
                const result = await response.json();
                
                clearInterval(stepTimer);

                if (response.ok && result.status === 'success') {
                    // Complete all steps visually
                    for (let i = currentStepIdx; i < steps.length; i++) {
                        setStepState(steps[i].elementId, 'done');
                    }
                    
                    // Redirect to preview
                    setTimeout(() => {
                        window.location.href = `/preview?session_id=${result.session_id}`;
                    }, 800);
                } else {
                    progressModal.hide();
                    alert(result.message || 'An error occurred during extraction.');
                }
            } catch (err) {
                clearInterval(stepTimer);
                progressModal.hide();
                console.error(err);
                alert('An error occurred during communication with the server.');
            }
        });
    }

    function setStepState(elementId, state) {
        const item = document.getElementById(elementId);
        if (!item) return;
        
        const iconContainer = item.querySelector('.status-icon');
        iconContainer.className = 'status-icon'; // reset
        
        if (state === 'pending') {
            iconContainer.classList.add('pending');
            iconContainer.innerHTML = '';
        } else if (state === 'loading') {
            iconContainer.classList.add('loading');
            iconContainer.innerHTML = '';
        } else if (state === 'done') {
            iconContainer.classList.add('done');
            iconContainer.innerHTML = '✓';
            item.classList.add('text-success');
        }
    }

    // ----------------------------------------------------
    // 3. Tamil / English Feedback Toggle on Results
    // ----------------------------------------------------
    const langToggle = document.getElementById('lang-toggle');
    if (langToggle) {
        langToggle.addEventListener('change', () => {
            const showTamil = langToggle.checked;
            
            const enTexts = document.querySelectorAll('.feedback-en');
            const taTexts = document.querySelectorAll('.feedback-ta');
            
            if (showTamil) {
                enTexts.forEach(el => el.classList.add('d-none'));
                taTexts.forEach(el => el.classList.remove('d-none'));
            } else {
                enTexts.forEach(el => el.classList.remove('d-none'));
                taTexts.forEach(el => el.classList.add('d-none'));
            }
        });
    }

    // ----------------------------------------------------
    // 4. Results Page Manual Mark Overrides
    // ----------------------------------------------------
    const overrideInputs = document.querySelectorAll('.override-marks-input');
    const updateMarksForm = document.getElementById('update-marks-form');

    if (overrideInputs.length > 0 && updateMarksForm) {
        const evalId = updateMarksForm.getAttribute('data-eval-id');
        const maxTotal = parseFloat(document.getElementById('max-total-score').innerText);

        overrideInputs.forEach(input => {
            input.addEventListener('change', async () => {
                const maxMarks = parseFloat(input.getAttribute('max'));
                let val = parseFloat(input.value);

                // Sanitize values
                if (isNaN(val) || val < 0) val = 0.0;
                if (val > maxMarks) val = maxMarks;
                input.value = val;

                // Submit to backend via AJAX
                const data = new FormData(updateMarksForm);
                try {
                    const response = await fetch(`/update-marks/${evalId}`, {
                        method: 'POST',
                        body: data
                    });
                    
                    const result = await response.json();
                    
                    if (response.ok && result.status === 'success') {
                        const newAwarded = result.new_total;
                        
                        // Update UI totals dynamically
                        document.getElementById('awarded-total-score').innerText = newAwarded.toFixed(1);
                        
                        // Recalculate percentage and update circular progress gauge
                        const percentage = maxTotal > 0 ? (newAwarded / maxTotal) * 100 : 0;
                        updateCircularGauge(percentage);
                    } else {
                        alert(result.message || 'Failed to update marks.');
                    }
                } catch (err) {
                    console.error(err);
                    alert('Error updating marks.');
                }
            });
        });
    }

    function updateCircularGauge(percentage) {
        const progressRing = document.querySelector('.gauge-progress');
        const textElement = document.querySelector('.gauge-percentage');
        
        if (!progressRing || !textElement) return;

        // Radial gauge has circumference = 2 * PI * r = 2 * 3.14159 * 70 = ~440
        const strokeDashOffset = 440 - (percentage / 100) * 440;
        progressRing.style.strokeDashoffset = strokeDashOffset;
        textElement.innerText = `${Math.round(percentage)}%`;
    }

    // Trigger initial circular gauge animation on page load
    setTimeout(() => {
        const ring = document.querySelector('.gauge-progress');
        if (ring) {
            const initialPercent = parseFloat(ring.getAttribute('data-percentage') || 0);
            updateCircularGauge(initialPercent);
        }
    }, 100);
});
