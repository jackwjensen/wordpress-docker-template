---
audience: dev
type: how-to
---

# Build a multilingual site with Polylang

## Language-aware navigation

Use `pll_current_language()` to detect the active language and render the matching nav links:

```php
$is_en = function_exists( 'pll_current_language' ) && pll_current_language() === 'en';
// Then use $is_en to conditionally render nav links with correct URLs and labels
```

## Permalinks

With `hide_default: true` (common config), the default language has no URL prefix while other
languages get `/en/`, `/de/`, etc.:

- Danish: `/category/post-slug/`
- English: `/en/category/post-slug/`

## A static front page per language

With a static front page (`page_on_front`), Polylang uses the translation relationship to decide
which page each language shows. Make sure:

1. Both language pages exist and are linked as translations in Polylang.
2. The `post_translations` taxonomy maps the two pages to each other.
3. The language switcher (`pll_the_languages()`) generates correct URLs for the front page.

## Loading WordPress from a script

Polylang needs `$_SERVER['HTTP_HOST']` and `$_SERVER['REQUEST_URI']` when WordPress loads
outside a web request. Set both before `require wp-load.php` in migration scripts or CLI tools,
or Polylang throws a fatal error.
