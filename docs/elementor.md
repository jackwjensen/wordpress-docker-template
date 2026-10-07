---
audience: dev
type: how-to
---

# Build a custom theme alongside Elementor

When building a custom child theme alongside Elementor, several non-obvious conflicts arise.

## Stop Theme Builder templates overriding your theme files

Elementor Pro's Theme Builder stores header, footer, single post, and archive templates as
`elementor_library` posts with `_elementor_conditions` postmeta. The condition `include/general`
(header/footer) or `include/singular` (single post) makes Elementor inject its template on ALL
matching pages — **independently of the WordPress template hierarchy**. Your custom `header.php`,
`single.php` and `page.php` files will be overridden or doubled.

<!-- standards: docs-stale-symbol exempt -- migrate.php is a file a site adds to its own theme; the template ships none -->
**Fix**: remove the conflicting template conditions from the database (in `migrate.php` — see
[database-changes.md](database-changes.md)):

```php
// Remove Elementor conditions for templates that conflict with theme files
$templates_to_disable = [ /* post IDs of Header, Footer, Single Post, Single Page templates */ ];
$ids = implode( ',', array_map( 'intval', $templates_to_disable ) );
$wpdb->query( "DELETE FROM {$wpdb->postmeta} WHERE post_id IN ($ids) AND meta_key = '_elementor_conditions'" );
$wpdb->query( "DELETE FROM {$wpdb->options} WHERE option_name LIKE '%elementor%conditions%'" );
```

To find the template IDs:

```sql
SELECT p.ID, p.post_title, pm.meta_value
FROM wp_posts p JOIN wp_postmeta pm ON p.ID = pm.post_id
WHERE p.post_type = 'elementor_library' AND pm.meta_key = '_elementor_conditions';
```

## Reclaim `template_include`

Elementor hooks into `template_include` at a high priority. Register your own filter at
priority **999**:

```php
add_filter( 'template_include', function( $template ) {
    if ( is_home() )             return locate_template( 'home.php' ) ?: $template;
    if ( is_category() )         return locate_template( 'category.php' ) ?: $template;
    if ( is_singular( 'post' ) ) return locate_template( 'single.php' ) ?: $template;
    // For pages: only override non-Elementor pages (let Elementor render its own pages like the front page)
    if ( is_page() && ! is_front_page() ) {
        $is_elementor = get_post_meta( get_queried_object_id(), '_elementor_edit_mode', true ) === 'builder';
        if ( ! $is_elementor ) return locate_template( 'page.php' ) ?: $template;
    }
    return $template;
}, 999 );
```

## Override Elementor's CSS

Elementor adds inline styles and high-specificity selectors to its widget wrappers
(`.elementor-element`, `.e-con`, `.elementor-widget`). Use `!important` on layout properties:

```css
.my-content-area .elementor-element { margin: 0 !important; padding: 0 !important; }
.my-content-area h2.elementor-heading-title { border-top: 1px solid #e2e8f0 !important; }
```

## Change Elementor page data from PHP

Elementor stores page content as JSON in the `_elementor_data` postmeta.

- **Never use `update_post_meta()` with `wp_slash()`** — it can double-escape the JSON and
  corrupt it. Use `$wpdb` directly; DELETE + INSERT is more reliable than UPDATE for large blobs:
  ```php
  $wpdb->query( $wpdb->prepare(
      "DELETE FROM {$wpdb->postmeta} WHERE post_id = %d AND meta_key = '_elementor_data'", $post_id
  ) );
  $wpdb->query( $wpdb->prepare(
      "INSERT INTO {$wpdb->postmeta} (post_id, meta_key, meta_value) VALUES (%d, '_elementor_data', %s)",
      $post_id, $json_string
  ) );
  ```
- **Clear ALL Elementor caches afterwards** — it caches rendered output in several places:
  ```php
  clean_post_cache( $post_id );
  wp_cache_flush();
  delete_post_meta( $post_id, '_elementor_css' );
  delete_post_meta( $post_id, '_elementor_page_assets' );
  // Also delete CSS files in uploads/elementor/css/post-{ID}*
  ```
- **Then clear it in the admin too** — Elementor → Tools → Clear Files & Data is the most
  thorough option — and purge the page cache (`wp litespeed-purge all`).
