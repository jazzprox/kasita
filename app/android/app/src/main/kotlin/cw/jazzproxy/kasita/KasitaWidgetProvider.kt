package cw.jazzproxy.kasita

import android.appwidget.AppWidgetManager
import android.content.Context
import android.content.SharedPreferences
import android.widget.RemoteViews
import es.antonborri.home_widget.HomeWidgetLaunchIntent
import es.antonborri.home_widget.HomeWidgetProvider

/** Home-screen widget: the open shopping list and what to use soon, as the app last saw them. */
class KasitaWidgetProvider : HomeWidgetProvider() {
    override fun onUpdate(
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
