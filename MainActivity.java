package vn.tan.dieukhien;

import android.app.Activity;
import android.content.pm.ActivityInfo;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

public class MainActivity extends Activity {
    private static final String HOME = "file:///android_asset/connect.html";
    private WebView web;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        web = new WebView(this);
        web.setBackgroundColor(0xFF0B0F14);
        setContentView(web);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setCacheMode(WebSettings.LOAD_NO_CACHE);
        s.setMediaPlaybackRequiresUserGesture(false);
        web.addJavascriptInterface(new Bridge(), "App");

        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedError(WebView v, WebResourceRequest req, WebResourceError err) {
                if (req.isForMainFrame() && !req.getUrl().toString().startsWith("file:")) {
                    v.loadUrl(HOME + "?err=" + Uri.encode(String.valueOf(err.getDescription())));
                }
            }
        });
        web.loadUrl(HOME);
    }

    private void goHome() {
        setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED);
        web.loadUrl(HOME);
    }

    @Override
    public void onBackPressed() {
        String u = web.getUrl();
        if (u != null && !u.startsWith("file:")) goHome();
        else super.onBackPressed();
    }

    @Override
    protected void onPause() { super.onPause(); web.onPause(); }

    @Override
    protected void onResume() { super.onResume(); web.onResume(); }

    class Bridge {
        @JavascriptInterface
        public void rotate() {
            runOnUiThread(() -> {
                boolean land = getRequestedOrientation() == ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE;
                setRequestedOrientation(land ? ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
                                             : ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE);
            });
        }

        @JavascriptInterface
        public void disconnect() { runOnUiThread(MainActivity.this::goHome); }

        @JavascriptInterface
        public String getCfg(String key) {
            return getSharedPreferences("cfg", MODE_PRIVATE).getString(key, "");
        }

        @JavascriptInterface
        public void setCfg(String key, String value) {
            getSharedPreferences("cfg", MODE_PRIVATE).edit().putString(key, value).apply();
        }

        @JavascriptInterface
        public void vibrate(int ms) {
            try {
                Vibrator v = (Vibrator) getSystemService(VIBRATOR_SERVICE);
                if (v == null) return;
                if (Build.VERSION.SDK_INT >= 26) v.vibrate(VibrationEffect.createOneShot(ms, VibrationEffect.DEFAULT_AMPLITUDE));
                else v.vibrate(ms);
            } catch (Exception ignored) { }
        }
    }
}
