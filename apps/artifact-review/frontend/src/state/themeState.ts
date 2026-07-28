import { useCallback, useEffect, useState } from 'react';

type Theme = 'light' | 'dark';

const THEME_STORAGE_KEY = 'review-serve-theme';

function readDocumentTheme(): Theme {
  return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
}

function applyTheme(theme: Theme): void {
  if (theme === 'dark') {
    document.documentElement.setAttribute('data-theme', 'dark');
  } else {
    document.documentElement.removeAttribute('data-theme');
  }

  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
  }
}

export function useTheme(): { readonly theme: Theme; readonly toggleTheme: () => void } {
  const [theme, setTheme] = useState<Theme>(() => readDocumentTheme());

  useEffect(() => {
    setTheme(readDocumentTheme());
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme((currentTheme) => {
      const nextTheme = currentTheme === 'dark' ? 'light' : 'dark';
      applyTheme(nextTheme);
      return nextTheme;
    });
  }, []);

  return { theme, toggleTheme };
}
