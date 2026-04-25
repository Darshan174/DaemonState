import os
import re

directories = ['/Users/darshann/Desktop/context-engine/frontend/src/pages', '/Users/darshann/Desktop/context-engine/frontend/src/components']

patterns = [
    # Backgrounds
    (r'(?<!dark:)bg-([a-z]+)-50(?!\d|/)', r'bg-\1-50 dark:bg-\1-900/30'),
    (r'(?<!dark:)bg-([a-z]+)-100(?!\d|/)', r'bg-\1-100 dark:bg-\1-900/40'),
    # Borders
    (r'(?<!dark:)border-([a-z]+)-200(?!\d|/)', r'border-\1-200 dark:border-\1-800/50'),
    (r'(?<!dark:)border-([a-z]+)-100(?!\d|/)', r'border-\1-100 dark:border-\1-800/30'),
    # Text
    (r'(?<!dark:)text-([a-z]+)-800(?!\d|/)', r'text-\1-800 dark:text-\1-300'),
    (r'(?<!dark:)text-([a-z]+)-700(?!\d|/)', r'text-\1-700 dark:text-\1-400'),
    (r'(?<!dark:)text-([a-z]+)-600(?!\d|/)', r'text-\1-600 dark:text-\1-400'),
    (r'(?<!dark:)text-([a-z]+)-900(?!\d|/)', r'text-\1-900 dark:text-\1-200'),
    # Backgrounds for elements like badges where text is white and bg is dark
    (r'(?<!dark:)bg-white(?!\d|/|-)', r'bg-white dark:bg-slate-800'),
    # Do not blindly replace bg-white/70 or text-white. 
]

for directory in directories:
    for filename in os.listdir(directory):
        if filename.endswith('.jsx'):
            filepath = os.path.join(directory, filename)
            with open(filepath, 'r') as f:
                content = f.read()
            
            new_content = content
            for pattern, repl in patterns:
                # Add negative lookahead so we don't duplicate if script is run twice
                # Wait, if "bg-amber-50 dark:bg-amber-900/30" exists, my regex (?<!dark:)bg-amber-50 will match bg-amber-50 and replace it, 
                # resulting in "bg-amber-50 dark:bg-amber-900/30 dark:bg-amber-900/30"!
                # To prevent this: only replace if not followed by " dark:"
                
                # regex fix:
                # (?<!dark:)bg-([a-z]+)-50(?!\d|/)(?!\s+dark:bg-\1)
                
                # Let's adjust pattern:
                p = pattern + r'(?!\s+dark:)'
                new_content = re.sub(p, repl, new_content)
                
            if new_content != content:
                with open(filepath, 'w') as f:
                    f.write(new_content)
                print(f"Updated {filename}")

