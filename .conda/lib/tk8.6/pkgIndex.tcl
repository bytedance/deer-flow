if {![package vsatisfies [package provide Tcl] 8.6.0]} return
package ifneeded Tk 8.6.15 [list load [file normalize [file join $dir .. libtk8.6.so]]]
