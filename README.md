# Screenshot automation and management tool

This project automates the process of capturing, updating, and managing screenshots for web applications. It uses *Playwright* to control Chromium, record user interactions, and capture consistent screenshots with minimal manual effort.

## Features

- Record mouse, keyboard, and scroll actions  
- Capture screenshots of selected or full viewports  
- Compare and replace only changed screenshots  
- Inject a browser overlay UI to manage entries  
- Add, edit, or delete screenshot entries directly from the browser  
- Store metadata in *screenshots.json*  
- Support bulk add, bulk delete, and JSON export  
- Display progress updates in the console  

## Project workflow

1. Launch the script.  
2. The browser opens the defined URL.  
3. The overlay UI appears in the browser.  
4. Use the overlay to record actions or select a clip area.  
5. Save entries to *screenshots.json*.  
6. Run the script again to capture screenshots automatically.  
7. The tool compares old and new images and updates only the changed files.  

## Requirements

- Python 3.9 or later  
- Playwright  
- Node.js (for Playwright dependencies)  

Install the dependencies by running:

```bash
pip install playwright
playwright install
```




project/

├── Scale4_screenshot.py

├── screenshots/

│   ├── captured_images.png

│   └── ...

├── screenshots.json

└── README.md


## Usage
```bash
To start the program:
python Scale4_screenshot.py
```


When the browser opens:

* Use the overlay to add or edit entries.
* Click Start Recording to begin capturing actions.
* Click Stop Recording to finish and select a clip region.
* Save the entry to screenshots.json.

* After recording entries, choose Take screenshots from the main menu to capture all images automatically.

> **Note:**
> * The URL is constant (single.mcns.io).
> * The tool supports both single and bulk JSON operations.
> * Screenshots are replaced only when differences are detected.
> * Logs show progress for every operation.

## Future enhancements

* Support for multiple URLs or environments
* Cloud upload for screenshots
* Integration with CI/CD pipelines
* Custom naming and tagging options
