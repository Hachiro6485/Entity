import webbrowser
import urllib.parse
import os

def search(query):
    print(f"DEBUG WEB_TOOLS: Attempting to open search for: '{query}'")
    
    query_lower = query.lower()
    if "youtube" in query_lower:
        clean_query = query_lower.replace("youtube", "").replace("search", "").strip()
        url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(clean_query)}"
    else:
        url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
    
    # Try multiple ways to open
    try:
        webbrowser.open(url)
        print("DEBUG WEB_TOOLS: webbrowser.open success")
    except Exception as e:
        print(f"DEBUG WEB_TOOLS: webbrowser failed, trying os.startfile. Error: {e}")
        os.startfile(url)
        
    return f"Searching for {query}."

def open_website(url):
    """
    Opens a website directly in the user's default browser.

    Unlike search(), this function never converts the URL into a
    search query. It simply opens the requested website.
    """

    url = str(url).strip()

    if not url:
        return "No website was specified."

    # Add HTTPS when the model gives us a normal domain without a scheme.
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        webbrowser.open(url)
        print(f"DEBUG WEB_TOOLS: Opening website directly: '{url}'")
        return f"Opening {url}."
    except Exception as e:
        print(f"DEBUG WEB_TOOLS: Failed to open website: {e}")

        try:
            os.startfile(url)
            return f"Opening {url}."
        except Exception as fallback_error:
            return f"I couldn't open {url}: {fallback_error}"