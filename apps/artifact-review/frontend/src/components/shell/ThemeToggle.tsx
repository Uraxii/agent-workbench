import { useEffect } from 'react';
import { useTheme } from '../../state/themeState';

function isTextInput(element: Element | null): boolean {
  return element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement || element instanceof HTMLSelectElement;
}

export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();

  useEffect(() => {
    function toggleThemeFromKeyboard(event: KeyboardEvent): void {
      if (isTextInput(document.activeElement)) {
        return;
      }

      if (event.key === 't' || event.key === 'T') {
        toggleTheme();
      }
    }

    document.addEventListener('keydown', toggleThemeFromKeyboard);
    return () => document.removeEventListener('keydown', toggleThemeFromKeyboard);
  }, [toggleTheme]);

  return (
    <button type="button" aria-label="Toggle light and dark theme" title="Toggle theme" className="theme-toggle" onClick={toggleTheme}>
      <svg className="icon"><use href={theme === 'dark' ? '#i-moon' : '#i-sun'} /></svg>
      <kbd>T</kbd>
    </button>
  );
}
