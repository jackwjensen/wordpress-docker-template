<?php
declare(strict_types=1);

/**
 * Writes /var/www/html/wp-config.php from the container's WORDPRESS_* environment.
 *
 * Runs at every container start (docker/openlitespeed/entrypoint.sh), as root, with the CLI PHP —
 * which, unlike lsphp behind OpenLiteSpeed, can see the environment. The official image's
 * wp-config.php reads the environment on every request instead; under LSAPI getenv() returns
 * false, so here the values are written into the file. Same result: the compose files stay the
 * single place the configuration is set, and a change there takes effect on the next start.
 *
 * Kept from the existing wp-config.php (also from one the official image or Duplicator wrote):
 * - the secret keys, so a restart or deploy never logs anyone out; only a fresh volume gets new
 *   ones (unless WORDPRESS_AUTH_KEY etc. are set);
 * - the table prefix, so a site imported with its own prefix keeps it (unless
 *   WORDPRESS_TABLE_PREFIX is set); a fresh volume gets wp_.
 *
 * Any failure exits non-zero, which stops the container start (the entrypoint runs under
 * set -e): a container that cannot write its configuration must not serve a stale one.
 */

const TARGET = '/var/www/html/wp-config.php';
const SALTS  = array( 'AUTH_KEY', 'SECURE_AUTH_KEY', 'LOGGED_IN_KEY', 'NONCE_KEY', 'AUTH_SALT', 'SECURE_AUTH_SALT', 'LOGGED_IN_SALT', 'NONCE_SALT' );

/** Stops the container start with a message when a filesystem call reported failure. */
function must( bool $succeeded, string $what ): void {
	if ( ! $succeeded ) {
		fwrite( STDERR, "make-wp-config.php: could not $what\n" );
		exit( 1 );
	}
}

/** The value of an environment variable, from VAR_FILE (Docker secrets) or VAR. */
function env( string $name, string $default ): string {
	$file = getenv( $name . '_FILE' );
	if ( false !== $file && '' !== $file ) {
		$secret = file_get_contents( $file );
		must( false !== $secret, "read {$name}_FILE ($file)" );
		return rtrim( $secret, "\r\n" );
	}
	$value = getenv( $name );
	return false === $value ? $default : $value;
}

$existing = '';
if ( file_exists( TARGET ) ) {
	$existing = file_get_contents( TARGET );
	must( false !== $existing, 'read the existing ' . TARGET );
}
$salts    = array();
foreach ( SALTS as $name ) {
	// Matches both forms: define( 'AUTH_KEY', '…' ) and the official image's
	// define( 'AUTH_KEY', getenv_docker( 'WORDPRESS_AUTH_KEY', '…' ) ).
	$pattern = "/define\(\s*'$name',\s*(?:getenv_docker\(\s*'WORDPRESS_$name',\s*)?'([^'\\\\]+)'/";
	$current = preg_match( $pattern, $existing, $m ) && 'put your unique phrase here' !== $m[1] ? $m[1] : '';
	$salts[ $name ] = env( "WORDPRESS_$name", '' ) ?: ( $current ?: bin2hex( random_bytes( 32 ) ) );
}

// Same two forms for the prefix: $table_prefix = 'x_'; and getenv_docker( '…', 'x_' ).
$prefix_pattern = "/\\\$table_prefix\s*=\s*(?:getenv_docker\(\s*'WORDPRESS_TABLE_PREFIX',\s*)?'([A-Za-z0-9_]+)'/";
$table_prefix   = env( 'WORDPRESS_TABLE_PREFIX', '' ) ?: ( preg_match( $prefix_pattern, $existing, $m ) ? $m[1] : 'wp_' );

// "true", "1", "yes", "on" switch debugging on; "false", "0", "" and anything else leave it off.
// (The official image treats ANY non-empty value as true — WORDPRESS_DEBUG=false included.)
$debug = filter_var( env( 'WORDPRESS_DEBUG', '' ), FILTER_VALIDATE_BOOLEAN );

$lit = static fn( string $value ): string => var_export( $value, true );

$config  = "<?php\n";
$config .= "// GENERATED at container start by docker/openlitespeed/make-wp-config.php from the compose files.\n";
$config .= "// Do not edit — change the WORDPRESS_* variables and restart the container instead.\n\n";
$config .= 'define( \'DB_NAME\', ' . $lit( env( 'WORDPRESS_DB_NAME', 'wordpress' ) ) . " );\n";
$config .= 'define( \'DB_USER\', ' . $lit( env( 'WORDPRESS_DB_USER', 'root' ) ) . " );\n";
$config .= 'define( \'DB_PASSWORD\', ' . $lit( env( 'WORDPRESS_DB_PASSWORD', '' ) ) . " );\n";
$config .= 'define( \'DB_HOST\', ' . $lit( env( 'WORDPRESS_DB_HOST', 'mysql' ) ) . " );\n";
$config .= 'define( \'DB_CHARSET\', ' . $lit( env( 'WORDPRESS_DB_CHARSET', 'utf8mb4' ) ) . " );\n";
$config .= 'define( \'DB_COLLATE\', ' . $lit( env( 'WORDPRESS_DB_COLLATE', '' ) ) . " );\n\n";
foreach ( $salts as $name => $value ) {
	$config .= "define( '$name', " . $lit( $value ) . " );\n";
}
$config .= "\n\$table_prefix = " . $lit( $table_prefix ) . ";\n";
$config .= "define( 'WP_DEBUG', " . ( $debug ? 'true' : 'false' ) . " );\n\n";
$config .= "// Behind a reverse proxy (production), which terminates TLS.\n";
$config .= "if ( isset( \$_SERVER['HTTP_X_FORWARDED_PROTO'] ) && str_contains( \$_SERVER['HTTP_X_FORWARDED_PROTO'], 'https' ) ) {\n";
$config .= "\t\$_SERVER['HTTPS'] = 'on';\n}\n\n";
$config .= "// WORDPRESS_CONFIG_EXTRA from the compose files:\n";
$config .= trim( env( 'WORDPRESS_CONFIG_EXTRA', '' ) ) . "\n\n";
$config .= "if ( ! defined( 'ABSPATH' ) ) {\n\tdefine( 'ABSPATH', __DIR__ . '/' );\n}\n";
$config .= "require_once ABSPATH . 'wp-settings.php';\n";

// Written next to the target and renamed into place, so lsphp never reads a half-written file.
$tmp = TARGET . '.tmp';
must( false !== file_put_contents( $tmp, $config ), "write $tmp" );
must( chown( $tmp, 'www-data' ) && chgrp( $tmp, 'www-data' ) && chmod( $tmp, 0640 ), "give $tmp to www-data" );
must( rename( $tmp, TARGET ), 'move the new wp-config.php into place' );
echo "wp-config.php written from the environment\n";
