# Retrofit and OkHttp ship consumer rules; keep API annotations and Room's
# generated database implementation discoverable in optimized release builds.
-keepattributes RuntimeVisibleAnnotations,RuntimeVisibleParameterAnnotations,AnnotationDefault
-keep class * extends androidx.room.RoomDatabase { *; }
-dontwarn org.codehaus.mojo.animal_sniffer.IgnoreJRERequirement
