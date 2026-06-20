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
    // Reusable Splash / Loading Screen Controller
    // ----------------------------------------------------
    const EvalIQSplash = {
        show: function(taglineText, showCredits = false) {
            const overlay = document.getElementById('evaliq-splash-screen');
            const tagline = document.getElementById('splash-tagline');
            const credits = document.getElementById('splash-credits');
            const progressContainer = document.getElementById('splash-progress-container');
            
            if (!overlay) return;
            
            tagline.textContent = taglineText || "AI-Powered Answer Sheet Evaluation";
            credits.style.display = showCredits ? 'block' : 'none';
            progressContainer.style.display = 'none'; // hidden by default
            
            overlay.style.display = 'flex';
            // Force reflow
            overlay.offsetHeight;
            overlay.style.opacity = '1';
        },
        
        hide: function() {
            const overlay = document.getElementById('evaliq-splash-screen');
            if (!overlay) return;
            
            overlay.style.opacity = '0';
            setTimeout(() => {
                overlay.style.display = 'none';
            }, 400);
        },
        
        updateStatus: function(statusText) {
            const tagline = document.getElementById('splash-tagline');
            if (tagline) {
                tagline.textContent = statusText;
            }
        },

        showBulkProgress: function(statusText, percentage) {
            const overlay = document.getElementById('evaliq-splash-screen');
            const tagline = document.getElementById('splash-tagline');
            const credits = document.getElementById('splash-credits');
            const progressContainer = document.getElementById('splash-progress-container');
            const progressBar = document.getElementById('splash-progress-bar');
            const progressPercent = document.getElementById('splash-progress-percent');
            const progressLeft = document.getElementById('splash-progress-left');
            
            if (!overlay) return;
            
            tagline.textContent = "Processing Bulk Evaluation Session...";
            credits.style.display = 'none';
            progressContainer.style.display = 'block';
            
            progressLeft.textContent = statusText;
            progressBar.style.width = `${percentage}%`;
            progressPercent.textContent = `${percentage}%`;
            
            overlay.style.display = 'flex';
            overlay.style.opacity = '1';
        }
    };

    // Expose to other scopes (e.g. inline scripts)
    window.EvalIQSplash = EvalIQSplash;

    // 1. Initial Page Load Splash Screen on Home Page (Upload page)
    if (window.location.pathname === '/' && !sessionStorage.getItem('splash_shown')) {
        EvalIQSplash.show("AI-Powered Answer Sheet Evaluation", true);
        sessionStorage.setItem('splash_shown', 'true');
        setTimeout(() => {
            EvalIQSplash.hide();
        }, 1800);
    }

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

            // Show EvalIQ splash screen as processing overlay
            const steps = [
                { name: 'Extracting Question Paper structure...' },
                { name: 'Extracting Answer Key rubrics...' },
                { name: 'Performing OCR on handwritten Answer Sheet...' },
                { name: 'Aligning questions and answers...' }
            ];

            EvalIQSplash.show(steps[0].name, false);

            // Progress simulator variables
            let currentStepIdx = 0;
            const stepTimer = setInterval(() => {
                if (currentStepIdx < steps.length - 1) {
                    currentStepIdx++;
                    EvalIQSplash.updateStatus(steps[currentStepIdx].name);
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
                    EvalIQSplash.updateStatus("Alignment complete! Loading preview...");
                    setTimeout(() => {
                        window.location.href = `/preview?session_id=${result.session_id}`;
                    }, 800);
                } else {
                    EvalIQSplash.hide();
                    alert(result.message || 'An error occurred during extraction.');
                }
            } catch (err) {
                clearInterval(stepTimer);
                EvalIQSplash.hide();
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

                        // Update PASS/FAIL badge dynamically
                        const passMarks = parseFloat(updateMarksForm.getAttribute('data-pass-marks')) || 0.0;
                        const totalMarks = parseFloat(updateMarksForm.getAttribute('data-total-marks')) || 0.0;
                        const badgeContainer = document.getElementById('pass-fail-badge-container');
                        const statusBadge = document.getElementById('pass-fail-status-badge');
                        if (totalMarks > 0 && badgeContainer && statusBadge) {
                            if (newAwarded >= passMarks) {
                                statusBadge.className = "badge bg-success py-2 px-3 fs-5 mb-2";
                                statusBadge.innerHTML = '<i class="fa-solid fa-circle-check me-1"></i>PASS';
                            } else {
                                statusBadge.className = "badge bg-danger py-2 px-3 fs-5 mb-2";
                                statusBadge.innerHTML = '<i class="fa-solid fa-circle-xmark me-1"></i>FAIL';
                            }
                        }
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
