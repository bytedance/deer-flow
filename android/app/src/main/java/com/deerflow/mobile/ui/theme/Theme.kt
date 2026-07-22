@file:OptIn(androidx.compose.material3.ExperimentalMaterial3ExpressiveApi::class)

package com.deerflow.mobile.ui.theme

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialExpressiveTheme
import androidx.compose.material3.MotionScheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.material3.Typography
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.unit.dp
import com.deerflow.mobile.data.ThemePreference

private val LightColors = lightColorScheme(
    primary = Color(0xFF276B45),
    onPrimary = Color.White,
    primaryContainer = Color(0xFFD8ECDE),
    onPrimaryContainer = Color(0xFF0A2A18),
    secondary = Color(0xFF315D78),
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFD9EAF5),
    onSecondaryContainer = Color(0xFF112C3C),
    tertiary = Color(0xFF8A5B18),
    background = Color(0xFFF7F8F5),
    onBackground = Color(0xFF19201B),
    surface = Color(0xFFF7F8F5),
    onSurface = Color(0xFF19201B),
    surfaceVariant = Color(0xFFE7EAE5),
    onSurfaceVariant = Color(0xFF424943),
    outline = Color(0xFF737A73),
    outlineVariant = Color(0xFFCACFC9),
    error = Color(0xFFB3261E),
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFFA8D5B5),
    onPrimary = Color(0xFF103722),
    primaryContainer = Color(0xFF1D5134),
    onPrimaryContainer = Color(0xFFD8ECDE),
    secondary = Color(0xFFA8CDE4),
    onSecondary = Color(0xFF173749),
    secondaryContainer = Color(0xFF294E64),
    onSecondaryContainer = Color(0xFFD9EAF5),
    tertiary = Color(0xFFE9C17F),
    background = Color(0xFF111512),
    onBackground = Color(0xFFE1E5E0),
    surface = Color(0xFF111512),
    onSurface = Color(0xFFE1E5E0),
    surfaceVariant = Color(0xFF292F2A),
    onSurfaceVariant = Color(0xFFC2C8C1),
    outline = Color(0xFF8C938C),
    outlineVariant = Color(0xFF3E453F),
)

private val DeerFlowTypography = Typography(
    headlineMedium = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.SemiBold,
        fontSize = 28.sp,
        lineHeight = 34.sp,
        letterSpacing = 0.sp,
    ),
    titleLarge = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.SemiBold,
        fontSize = 21.sp,
        lineHeight = 27.sp,
        letterSpacing = 0.sp,
    ),
    titleMedium = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.SemiBold,
        fontSize = 16.sp,
        lineHeight = 22.sp,
        letterSpacing = 0.sp,
    ),
    bodyLarge = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.Normal,
        fontSize = 16.sp,
        lineHeight = 24.sp,
        letterSpacing = 0.sp,
    ),
    bodyMedium = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.Normal,
        fontSize = 14.sp,
        lineHeight = 20.sp,
        letterSpacing = 0.sp,
    ),
    labelLarge = TextStyle(
        fontFamily = FontFamily.SansSerif,
        fontWeight = FontWeight.Medium,
        fontSize = 14.sp,
        lineHeight = 20.sp,
        letterSpacing = 0.sp,
    ),
)

private val DeerFlowShapes = Shapes(
    extraSmall = RoundedCornerShape(8.dp),
    small = RoundedCornerShape(12.dp),
    medium = RoundedCornerShape(16.dp),
    large = RoundedCornerShape(24.dp),
    extraLarge = RoundedCornerShape(32.dp),
)

@Composable
fun DeerFlowTheme(
    preference: ThemePreference = ThemePreference.System,
    useDynamicColor: Boolean = true,
    content: @Composable () -> Unit,
) {
    val dark = when (preference) {
        ThemePreference.System -> isSystemInDarkTheme()
        ThemePreference.Light -> false
        ThemePreference.Dark -> true
    }
    val context = LocalContext.current
    val colors = when {
        useDynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && dark -> dynamicDarkColorScheme(context)
        useDynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> dynamicLightColorScheme(context)
        dark -> DarkColors
        else -> LightColors
    }
    MaterialExpressiveTheme(
        colorScheme = colors,
        motionScheme = MotionScheme.expressive(),
        typography = DeerFlowTypography,
        shapes = DeerFlowShapes,
        content = content,
    )
}
