<?php
/**
 * License verifier for WordPress plugins/themes.
 *
 * Usage from the plugin/theme bootstrap:
 *
 *   require_once __DIR__ . '/inc/class-license.php';
 *   $license = new \Pcreative\License('__SLUG__');
 *   if (!$license->is_active()) {
 *       add_action('admin_notices', [$license, 'render_inactive_notice']);
 *   }
 */

namespace ThemeForge\Licensing;

defined('ABSPATH') || exit;

class License
{
    const API_URL = '__LICENSE_API_URL__';

    private string $product;
    private string $option_key;

    public function __construct(string $product_slug)
    {
        $this->product    = $product_slug;
        $this->option_key = "themeforge_license_{$product_slug}";
    }

    public function is_active(): bool
    {
        $state = $this->get_state();
        return !empty($state['valid']);
    }

    public function get_key(): string
    {
        $state = $this->get_state();
        return (string)($state['license_key'] ?? '');
    }

    public function get_state(): array
    {
        $state = get_option($this->option_key, []);
        return is_array($state) ? $state : [];
    }

    public function activate(string $key): array
    {
        $response = wp_remote_post(self::API_URL, [
            'timeout' => 10,
            'headers' => ['Content-Type' => 'application/json'],
            'body'    => wp_json_encode([
                'license_key' => $key,
                'product'     => $this->product,
                'domain'      => $this->host(),
                'action'      => 'activate',
            ]),
        ]);

        if (is_wp_error($response)) {
            return [
                'valid' => false,
                'error' => 'License server unreachable.',
            ];
        }

        $body = json_decode(wp_remote_retrieve_body($response), true);
        if (!is_array($body)) {
            return ['valid' => false, 'error' => 'Bad response.'];
        }

        if (!empty($body['valid'])) {
            update_option($this->option_key, array_merge($body, [
                'license_key' => $key,
                'host'        => $this->host(),
                'activated_at' => time(),
            ]));
        }

        return $body;
    }

    public function deactivate(): array
    {
        $key = $this->get_key();
        delete_option($this->option_key);

        if (!$key) {
            return ['valid' => false];
        }
        $response = wp_remote_post(self::API_URL, [
            'timeout' => 10,
            'headers' => ['Content-Type' => 'application/json'],
            'body'    => wp_json_encode([
                'license_key' => $key,
                'product'     => $this->product,
                'domain'      => $this->host(),
                'action'      => 'deactivate',
            ]),
        ]);
        if (is_wp_error($response)) {
            return ['ok' => false];
        }
        return json_decode(wp_remote_retrieve_body($response), true) ?: [];
    }

    public function render_inactive_notice(): void
    {
        ?>
        <div class="notice notice-warning">
            <p><strong><?php echo esc_html($this->product); ?></strong>: license not active.
            Go to <a href="<?php echo esc_url(admin_url('admin.php?page=' . $this->product . '-license')); ?>">License settings</a>.</p>
        </div>
        <?php
    }

    private function host(): string
    {
        return parse_url(home_url(), PHP_URL_HOST) ?: 'localhost';
    }
}
