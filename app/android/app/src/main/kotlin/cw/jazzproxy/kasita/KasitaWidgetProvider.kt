package cw.jazzproxy.kasita

import android.appwidget.AppWidgetManager
import android.content.Context
import android.content.SharedPreferences
import android.widget.RemoteViews
import es.antonborri.home_widget.HomeWidgetLaunchIntent
import es.antonborri.home_widget.HomeWidgetProvider
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Home-screen widget: the open shopping list and what to use soon.
 *
 * Android calls onUpdate every 30 minutes (updatePeriodMillis). The widget first
 * draws what it has, then fetches fresh data from Kasita in the background with
 * its own read-only key (created by the app) and redraws.
 */
class KasitaWidgetProvider : HomeWidgetProvider() {
    override fun onUpdate(
        context: Context,
        appWidgetManager: AppWidgetManager,
        appWidgetIds: IntArray,
        widgetData: SharedPreferences,
    ) {
        draw(context, appWidgetManager, appWidgetIds, widgetData)

        val server = widgetData.getString("kasita_server", null)
        val hid = widgetData.getString("kasita_hid", null)
        val key = widgetData.getString("kasita_key", null)
        if (server.isNullOrEmpty() || hid.isNullOrEmpty() || key.isNullOrEmpty()) return

        val pending = goAsync() // keep the receiver alive while fetching (a few seconds at most)
        Thread {
            try {
                val conn = URL("${server.trimEnd('/')}/api/households/$hid/widget").openConnection() as HttpURLConnection
                conn.connectTimeout = 8000
                conn.readTimeout = 8000
                conn.setRequestProperty("X-Api-Key", key)
                conn.setRequestProperty("Accept", "application/json")
                if (conn.responseCode == 200) {
                    val json = JSONObject(conn.inputStream.bufferedReader().use { it.readText() })
                    widgetData.edit()
                        .putString("shopping_title", json.optString("shopping_title", "Shopping list"))
                        .putString("shopping", json.optString("shopping", ""))
                        .putString("soon", json.optString("soon", ""))
                        .apply()
                    draw(context, appWidgetManager, appWidgetIds, widgetData)
                }
                conn.disconnect()
            } catch (e: Exception) {
                // offline: keep showing the last data
            } finally {
                pending.finish()
            }
        }.start()
    }

    private fun draw(
        context: Context,
        appWidgetManager: AppWidgetManager,
        appWidgetIds: IntArray,
        widgetData: SharedPreferences,
    ) {
        for (id in appWidgetIds) {
            val views = RemoteViews(context.packageName, R.layout.kasita_widget).apply {
                setTextViewText(R.id.widget_shopping_title, widgetData.getString("shopping_title", "Shopping list"))
                setTextViewText(R.id.widget_shopping, widgetData.getString("shopping", "Open Kasita once to fill this in"))
                setTextViewText(R.id.widget_soon, widgetData.getString("soon", ""))
                setOnClickPendingIntent(
                    R.id.widget_root,
                    HomeWidgetLaunchIntent.getActivity(context, MainActivity::class.java),
                )
            }
            appWidgetManager.updateAppWidget(id, views)
        }
    }
}
