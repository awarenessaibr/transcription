/**
 * Runpod Serverless Endpoint - JavaScript/Node.js Client
 * Example: Call the transcription-transcription endpoint for audio diarization
 */

const RUNPOD_API_KEY = "<YOUR_RUNPOD_API_KEY_HERE>";
const ENDPOINT_ID = "5j22h5dqpbj6kh";

// Synchronous endpoint (waits for completion)
const SYNC_URL = `https://api.runpod.ai/v2/${ENDPOINT_ID}/runsync`;

// Asynchronous endpoint (returns job ID, poll for result)
const ASYNC_URL = `https://api.runpod.ai/v2/${ENDPOINT_ID}/run`;
const STATUS_URL = (jobId) => `https://api.runpod.ai/v2/${ENDPOINT_ID}/status/${jobId}`;


/**
 * Call diarization excerpt using server-side file path (synchronous)
 */
async function callExcerptByPath(filePath, start, end, minSpeakers = 1, maxSpeakers = 2) {
  const requestConfig = {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${RUNPOD_API_KEY}`
    },
    body: JSON.stringify({
      "input": {
        "task": "excerpt",
        "file_path": filePath,
        "start": start,
        "end": end,
        "min_speakers": minSpeakers,
        "max_speakers": maxSpeakers
      }
    })
  };

  try {
    console.log(`Calling excerpt diarization: ${filePath} [${start}s - ${end}s]`);
    const response = await fetch(SYNC_URL, requestConfig);
    
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    
    const data = await response.json();
    console.log('Response:', JSON.stringify(data, null, 2));
    return data;
  } catch (error) {
    console.error('Error:', error);
    throw error;
  }
}


/**
 * Call diarization excerpt with base64-encoded audio upload (synchronous)
 */
async function callExcerptWithUpload(audioBase64, filename, start, end, minSpeakers = 1, maxSpeakers = 2) {
  const requestConfig = {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${RUNPOD_API_KEY}`
    },
    body: JSON.stringify({
      "input": {
        "task": "excerpt",
        "audio_base64": audioBase64,
        "filename": filename,
        "start": start,
        "end": end,
        "min_speakers": minSpeakers,
        "max_speakers": maxSpeakers
      }
    })
  };

  try {
    console.log(`Calling excerpt diarization with upload: ${filename} [${start}s - ${end}s]`);
    const response = await fetch(SYNC_URL, requestConfig);
    
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    
    const data = await response.json();
    console.log('Response:', JSON.stringify(data, null, 2));
    return data;
  } catch (error) {
    console.error('Error:', error);
    throw error;
  }
}


/**
 * Call diarization excerpt asynchronously (returns job ID)
 */
async function callExcerptAsync(filePath, start, end, minSpeakers = 1, maxSpeakers = 2) {
  const requestConfig = {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${RUNPOD_API_KEY}`
    },
    body: JSON.stringify({
      "input": {
        "task": "excerpt",
        "file_path": filePath,
        "start": start,
        "end": end,
        "min_speakers": minSpeakers,
        "max_speakers": maxSpeakers
      }
    })
  };

  try {
    console.log(`Starting async job: ${filePath} [${start}s - ${end}s]`);
    const response = await fetch(ASYNC_URL, requestConfig);
    
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    
    const data = await response.json();
    console.log('Job started:', data);
    return data.id; // Return job ID
  } catch (error) {
    console.error('Error:', error);
    throw error;
  }
}


/**
 * Poll job status until completion
 */
async function pollJobStatus(jobId, maxAttempts = 60, intervalMs = 2000) {
  const requestConfig = {
    method: "GET",
    headers: {
      "Authorization": `Bearer ${RUNPOD_API_KEY}`
    }
  };

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    try {
      const response = await fetch(STATUS_URL(jobId), requestConfig);
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const data = await response.json();
      console.log(`Job ${jobId} status: ${data.status}`);

      if (data.status === 'COMPLETED') {
        console.log('Job completed!');
        return data.output;
      } else if (data.status === 'FAILED') {
        throw new Error(`Job failed: ${data.error || 'Unknown error'}`);
      }

      // Wait before next poll
      await new Promise(resolve => setTimeout(resolve, intervalMs));
    } catch (error) {
      console.error('Error polling status:', error);
      throw error;
    }
  }

  throw new Error('Job timed out');
}


/**
 * Helper: Read local file and encode to base64 (Node.js)
 */
async function encodeFileToBase64(filePath) {
  const fs = require('fs').promises;
  const fileBuffer = await fs.readFile(filePath);
  return fileBuffer.toString('base64');
}


// ============================================================
// Example Usage
// ============================================================

async function main() {
  console.log('='.repeat(60));
  console.log('Example 1: Synchronous call with server-side path');
  console.log('='.repeat(60));

  try {
    const result1 = await callExcerptByPath(
      "/workspace/data/originals/yourfile.wav",
      15.0,
      30.0,
      1,
      2
    );
    console.log('Success:', result1);
  } catch (error) {
    console.error('Failed:', error);
  }

  console.log('\n' + '='.repeat(60));
  console.log('Example 2: Asynchronous call with job polling');
  console.log('='.repeat(60));

  try {
    const jobId = await callExcerptAsync(
      "/workspace/data/originals/yourfile.wav",
      0.0,
      15.0,
      1,
      3
    );
    
    console.log(`Polling job ${jobId}...`);
    const result2 = await pollJobStatus(jobId);
    console.log('Success:', result2);
  } catch (error) {
    console.error('Failed:', error);
  }

  /* 
  // Example 3: Upload local file (Node.js only)
  console.log('\n' + '='.repeat(60));
  console.log('Example 3: Upload local audio file');
  console.log('='.repeat(60));

  try {
    const audioBase64 = await encodeFileToBase64('./local_audio.mp3');
    const result3 = await callExcerptWithUpload(
      audioBase64,
      'local_audio.mp3',
      0.0,
      10.0,
      1,
      2
    );
    console.log('Success:', result3);
  } catch (error) {
    console.error('Failed:', error);
  }
  */
}

// Run examples
main()
  .then(() => console.log('\n✅ All examples completed'))
  .catch(error => console.error('\n❌ Error:', error));
