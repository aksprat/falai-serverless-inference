import os
import time
import requests
from flask import Flask, request, jsonify, Response

# --- Configuration ---

# Your DigitalOcean Model Access Key
# IMPORTANT: Do not hardcode this. Set it as an environment variable
# in your DigitalOcean App Platform settings.
MODEL_ACCESS_KEY = os.environ.get("MODEL_ACCESS_KEY")

# The DigitalOcean Serverless Inference API endpoint
DO_API_URL = "https://inference.do-ai.run/v1/async-invoke"

# The model we want to use
MODEL_ID = "fal-ai/flux/schnell"

# How long to wait between polling for results
POLL_INTERVAL = 3 # 3 seconds

# --- Flask App ---

app = Flask(__name__)

# --- HTML Frontend ---

# This is the simple webpage that will be served.
# It includes Tailwind CSS for basic styling.
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Fal AI Image Generator</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        .loader {
            border: 4px solid rgba(255, 255, 255, 0.3);
            border-top-color: #3498db;
            border-radius: 50%;
            width: 24px;
            height: 24px;
            animation: spin 1s linear infinite;
        }
    </style>
</head>
<body class="bg-gray-900 text-white font-sans min-h-screen flex items-center justify-center p-4">
    <div class="w-full max-w-2xl bg-gray-800 rounded-lg shadow-xl p-6 md:p-8">
        <h1 class="text-3xl font-bold text-center mb-6 text-blue-400">DigitalOcean + Fal AI Image Gen</h1>
        
        <!-- Input Form -->
        <form id="image-form" class="space-y-4">
            <div>
                <label for="prompt" class="block text-sm font-medium mb-2">Enter your prompt:</label>
                <textarea id="prompt" name="prompt" rows="3" class="w-full p-3 bg-gray-700 border border-gray-600 rounded-lg focus:ring-2 focus:ring-blue-500 focus:outline-none text-white" placeholder="e.g., A photo of a cat programming on a laptop"></textarea>
            </div>
            <button type="submit" id="generate-btn" class="w-full flex items-center justify-center bg-blue-600 hover:bg-blue-700 text-white font-bold py-3 px-4 rounded-lg transition duration-300">
                <span id="btn-text">Generate Image</span>
                <div id="loader" class="loader hidden ml-2"></div>
            </button>
        </form>
        
        <!-- Message/Error Area -->
        <div id="message" class="mt-4 text-center text-red-400"></div>
        
        <!-- Result Area -->
        <div id="result" class="mt-6 hidden">
            <h2 class="text-xl font-semibold mb-3">Your Image:</h2>
            <div class="bg-gray-700 rounded-lg p-2">
                <img id="result-image" src="" alt="Generated Image" class="w-full h-auto rounded-md">
            </div>
            <a id="result-link" href="#" target="_blank" class="block text-center mt-3 text-blue-400 hover:underline">View Full Size</a>
        </div>
    </div>

    <script>
        const form = document.getElementById('image-form');
        const generateBtn = document.getElementById('generate-btn');
        const btnText = document.getElementById('btn-text');
        const loader = document.getElementById('loader');
        const messageEl = document.getElementById('message');
        const resultEl = document.getElementById('result');
        const resultImage = document.getElementById('result-image');
        const resultLink = document.getElementById('result-link');

        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const prompt = document.getElementById('prompt').value;

            if (!prompt) {
                showMessage('Please enter a prompt.');
                return;
            }

            // --- Set loading state ---
            setLoading(true);

            try {
                // --- Call our own backend proxy ---
                const response = await fetch('/generate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ prompt: prompt })
                });

                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.error || 'An unknown error occurred.');
                }

                const data = await response.json();

                // --- Display the result ---
                if (data.imageUrl) {
                    resultImage.src = data.imageUrl;
                    resultLink.href = data.imageUrl;
                    resultEl.classList.remove('hidden');
                    showMessage(''); // Clear any old errors
                } else {
                    throw new Error('Backend did not return an image URL.');
                }

            } catch (error) {
                console.error('Error:', error);
                showMessage(error.message);
                resultEl.classList.add('hidden');
            } finally {
                // --- Unset loading state ---
                setLoading(false);
            }
        });

        function setLoading(isLoading) {
            if (isLoading) {
                generateBtn.disabled = true;
                btnText.textContent = 'Generating...';
                loader.classList.remove('hidden');
            } else {
                generateBtn.disabled = false;
                btnText.textContent = 'Generate Image';
                loader.classList.add('hidden');
            }
        }

        function showMessage(message) {
            messageEl.textContent = message;
        }
    </script>
</body>
</html>
"""

# --- API Routes ---

@app.route("/")
def home():
    """Serves the main HTML page."""
    return Response(HTML_CONTENT, mimetype='text/html')


@app.route("/generate", methods=["POST"])
def generate_image():
    """
    The backend proxy endpoint.
    1. Takes a 'prompt' from the client.
    2. Submits the job to DigitalOcean.
    3. Polls for completion.
    4. Returns the final image URL.
    """
    
    if not MODEL_ACCESS_KEY:
        return jsonify({"error": "Server is missing MODEL_ACCESS_KEY environment variable."}), 500

    try:
        data = request.json
        prompt = data.get("prompt")
        if not prompt:
            return jsonify({"error": "No prompt provided."}), 400

        headers = {
            "Authorization": f"Bearer {MODEL_ACCESS_KEY}",
            "Content-Type": "application/json"
        }
        
        # --- 1. Submit the async job ---
        payload = {
            "model_id": MODEL_ID,
            "input": {
                "prompt": prompt,
                "output_format": "landscape_4_3" # You can change this
            }
        }
        
        submit_response = requests.post(DO_API_URL, headers=headers, json=payload)
        submit_response.raise_for_status() # Raise error on bad status
        
        submit_data = submit_response.json()
        request_id = submit_data.get("request_id")
        
        if not request_id:
            return jsonify({"error": "Failed to submit job to DO."}), 500

        # --- 2. Poll for the result ---
        status_url = f"{DO_API_URL}/{request_id}/status"
        result_url = f"{DO_API_URL}/{request_id}"
        
        start_time = time.time()
        timeout = 120 # 2 minutes timeout
        
        while True:
            # Check for timeout
            if time.time() - start_time > timeout:
                return jsonify({"error": "Request timed out while waiting for model."}), 504

            status_response = requests.get(status_url, headers=headers)
            status_response.raise_for_status()
            status_data = status_response.json()

            status = status_data.get("status")

            if status == "COMPLETE":
                break # Exit loop, job is done
            elif status in ["FAILED", "ERROR"]:
                return jsonify({"error": "Model generation failed."}), 500
            
            # Wait before polling again
            time.sleep(POLL_INTERVAL)

        # --- 3. Fetch the final result ---
        result_response = requests.get(result_url, headers=headers)
        result_response.raise_for_status()
        result_data = result_response.json()
        
        # --- 4. Extract and return the image URL ---
        # The structure can be complex, let's find the image URL
        # Based on DO docs, it should be in `result["output"]["images"][0]["url"]`
        try:
            image_url = result_data["result"]["output"]["images"][0]["url"]
            return jsonify({"imageUrl": image_url})
        except (KeyError, IndexError, TypeError):
            print("Unexpected result structure:", result_data)
            return jsonify({"error": "Could not parse image URL from model response."}), 500

    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return jsonify({"error": f"API request failed: {e}"}), 502
    except Exception as e:
        print(f"An error occurred: {e}")
        return jsonify({"error": f"An internal server error occurred: {e}"}), 500

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
