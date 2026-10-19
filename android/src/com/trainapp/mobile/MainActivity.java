package com.trainapp.mobile;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.view.Window;
import android.webkit.JavascriptInterface;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;

/**
 * MainActivity — WebView 宿主。
 * 页面(assets/)内自带完整的 JS 引擎与离线数据, 本类只提供:
 *   1. AndroidHost.httpGet(url, headersJson): 原生 HTTP 桥(供 12306/携程实时查价,
 *      可设 Cookie/Referer 头, 无 CORS 限制), 同步返回 JSON:
 *      {"status":200,"body":"...","set_cookie":"k=v; k2=v2"} 或 {"error":"..."}
 *   2. 返回键接管: WebView 可后退则后退, 否则双击退出。
 */
public class MainActivity extends Activity {

    private static final String TAG = "TrainApp";
    private WebView web;
    private long lastBackAt = 0;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Window w = getWindow();
        w.setStatusBarColor(Color.parseColor("#0f1420"));
        w.setNavigationBarColor(Color.parseColor("#0f1420"));

        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        // 页面在 file:// 下; 允许 file 域访问外网(查 12306/携程)与自身资源
        s.setAllowFileAccessFromFileURLs(true);
        s.setAllowUniversalAccessFromFileURLs(true);
        s.setAllowFileAccess(true);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);
        s.setForceDark(WebSettings.FORCE_DARK_OFF);   // 页面自带深色配色, 别让系统反色搅乱
        if (Build.VERSION.SDK_INT >= 33) {
            s.setAlgorithmicDarkeningAllowed(false);
        }
        s.setUserAgentString("Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
                + "(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36 TrainApp/1.0");

        web.addJavascriptInterface(new Host(), "AndroidHost");
        web.setWebViewClient(new WebViewClient());
        web.loadUrl("file:///android_asset/index.html");
        setContentView(web);
    }

    private class Host {

        /** 同步 HTTP GET。headersJson: {"Key":"Value",...}; 返回 JSON 字符串。 */
        @JavascriptInterface
        public String httpGet(String url, String headersJson) {
            HttpURLConnection conn = null;
            try {
                URL u = new URL(url);
                conn = (HttpURLConnection) u.openConnection();
                conn.setConnectTimeout(10000);
                conn.setReadTimeout(15000);
                conn.setInstanceFollowRedirects(true);
                conn.setRequestMethod("GET");
                org.json.JSONObject hs = new org.json.JSONObject(headersJson);
                java.util.Iterator<String> it = hs.keys();
                while (it.hasNext()) {
                    String k = it.next();
                    if (!"Cookie".equalsIgnoreCase(k)) {
                        conn.setRequestProperty(k, hs.optString(k));
                    }
                }
                // Cookie 单独设, 保证会话正确下发
                String cookie = hs.optString("Cookie", null);
                if (cookie != null && cookie.length() > 0) {
                    conn.setRequestProperty("Cookie", cookie);
                }
                int status = conn.getResponseCode();
                InputStream is = status >= 400 ? conn.getErrorStream() : conn.getInputStream();
                String body = readAll(is);
                StringBuilder sc = new StringBuilder();
                Map<String, List<String>> hh = conn.getHeaderFields();
                if (hh != null) {
                    List<String> setc = hh.get("Set-Cookie");
                    if (setc == null) {
                        for (String key : hh.keySet()) {
                            if ("Set-Cookie".equalsIgnoreCase(key)) { setc = hh.get(key); break; }
                        }
                    }
                    if (setc != null) {
                        for (String c : setc) {
                            String kv = c.split(";")[0].trim();
                            if (kv.length() > 0) {
                                if (sc.length() > 0) sc.append("; ");
                                sc.append(kv);
                            }
                        }
                    }
                }
                org.json.JSONObject out = new org.json.JSONObject();
                out.put("status", status);
                out.put("body", body);
                if (sc.length() > 0) out.put("set_cookie", sc.toString());
                return out.toString();
            } catch (Exception e) {
                try {
                    return new org.json.JSONObject()
                            .put("error", e.getClass().getSimpleName() + ": " + e.getMessage()).toString();
                } catch (Exception x) {
                    return "{\"error\":\"http\"}";
                }
            } finally {
                if (conn != null) conn.disconnect();
            }
        }

        private String readAll(InputStream is) throws Exception {
            if (is == null) return "";
            BufferedReader br = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder();
            char[] buf = new char[8192];
            int n;
            while ((n = br.read(buf)) > 0) sb.append(buf, 0, n);
            br.close();
            return sb.toString();
        }
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
            return;
        }
        long now = System.currentTimeMillis();
        if (now - lastBackAt < 2000) {
            super.onBackPressed();
        } else {
            lastBackAt = now;
            Toast.makeText(this, "再按一次退出", Toast.LENGTH_SHORT).show();
        }
    }

    @Override
    protected void onDestroy() {
        if (web != null) {
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }
}
