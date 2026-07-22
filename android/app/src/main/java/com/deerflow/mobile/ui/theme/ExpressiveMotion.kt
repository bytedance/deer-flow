package com.deerflow.mobile.ui.theme

import androidx.compose.animation.core.FiniteAnimationSpec
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.spring

object ExpressiveMotion {
    fun <T> spatial(): FiniteAnimationSpec<T> = spring(
        dampingRatio = 0.72f,
        stiffness = Spring.StiffnessMediumLow,
    )

    fun <T> fastSpatial(): FiniteAnimationSpec<T> = spring(
        dampingRatio = 0.76f,
        stiffness = Spring.StiffnessMedium,
    )
}
