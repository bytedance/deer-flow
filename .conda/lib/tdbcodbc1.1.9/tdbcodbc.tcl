# tdbcodbc.tcl --
#
#	Class definitions and Tcl-level methods for the tdbc::odbc bridge.
#
# Copyright (c) 2008 by Kevin B. Kenny
# See the file "license.terms" for information on usage and redistribution
# of this file, and for a DISCLAIMER OF ALL WARRANTIES.
#
# RCS: @(#) $Id: tdbcodbc.tcl,v 1.47 2008/02/27 02:08:27 kennykb Exp $
#
#------------------------------------------------------------------------------

package require tdbc

::namespace eval ::tdbc::odbc {

    namespace export connection datasources drivers

    # Data types that are predefined in ODBC

    variable sqltypes [dict create \
			   1 char \
			   2 numeric \
			   3 decimal \
			   4 integer \
			   5 smallint \
			   6 float \
			   7 real \
			   8 double \
			   9 datetime \
			   12 varchar \
			   91 date \
			   92 time \
			   93 timestamp \
			   -1 longvarchar \
			   -2 binary \
			   -3 varbinary \
			   -4 longvarbinary \
			   -5 bigint \
			   -6 tinyint \
			   -7 bit \
			   -8 wchar \
			   -9 wvarchar \
			   -10 wlongvarchar \
			   -11 guid]
}

#------------------------------------------------------------------------------
#
# tdbc::odbc::connection --
#
#	Class representing a connection to a database through ODBC.
#
#-------------------------------------------------------------------------------

::oo::class create ::tdbc::odbc::connection {

    superclass ::tdbc::connection

    variable statementSeq typemap

    # The constructor is written in C. It takes the connection string
    # as its argument It sets up a namespace to hold the statements
    # associated with the connection, and then delegates to the 'init'
    # method (written in C) to do the actual work of attaching to the
    # database. When that comes back, it sets up a statement to query
    # the support types, makes a dictionary to enumerate them, and
    # calls back to set a flag if WVARCHAR is seen (If WVARCHAR is
    # seen, the database supports Unicode.)

    # The 'statementCreate' method forwards to the constructor of the
    # statement class

    forward statementCreate ::tdbc::odbc::statement create

    # The 'tables' method returns a dictionary describing the tables
    # in the database

    method tables {{pattern %}} {
	set stmt [::tdbc::odbc::tablesStatement create \
		      Stmt::[incr statementSeq] [self] $pattern]
       	set status [catch {
	    set retval {}
	    $stmt foreach -as dicts row {
		if {[dict exists $row TABLE_NAME]} {
		    dict set retval [dict get $row TABLE_NAME] $row
		}
	    }
	    set retval
	} result options]
	catch {rename $stmt {}}
	return -level 0 -options $options $result
    }

    # The 'columns' method returns a dictionary describing the tables
    # in the database

    method columns {table {pattern %}} {
	# Make sure that the type map is initialized
	my typemap

	# Query the columns from the database

	set stmt [::tdbc::odbc::columnsStatement create \
		      Stmt::[incr statementSeq] [self] $table $pattern]
	set status [catch {
	    set retval {}
	    $stmt foreach -as dicts origrow {

		# Map the type, precision, scale and nullable indicators
		# to tdbc's notation

		set row {}
		dict for {key value} $origrow {
		    dict set row [string tolower $key] $value
		}
		if {[dict exists $row column_name]} {
		    if {[dict exists $typemap \
			     [dict get $row data_type]]} {
			dict set row type \
			    [dict get $typemap \
				 [dict get $row data_type]]
		    } else {
			dict set row type [dict get $row type_name]
		    }
		    if {[dict exists $row column_size]} {
			dict set row precision \
			    [dict get $row column_size]
		    }
		    if {[dict exists $row decimal_digits]} {
			dict set row scale \
			    [dict get $row decimal_digits]
		    }
		    if {![dict exists $row nullable]} {
			dict set row nullable \
			    [expr {!![string trim [dict get $row is_nullable]]}]
		    }
		    dict set retval [dict get $row column_name] $row
		}
	    }
	    set retval
	} result options]
	catch {rename $stmt {}}
	return -level 0 -options $options $result
    }

    # The 'primarykeys' method returns a dictionary describing the primary
    # keys of a table

    method primarykeys {tableName} {
	set stmt [::tdbc::odbc::primarykeysStatement create \
		      Stmt::[incr statementSeq] [self] $tableName]
       	set status [catch {
	    set retval {}
	    $stmt foreach -as dicts row {
		foreach {odbcKey tdbcKey} {
		    TABLE_CAT		tableCatalog
		    TABLE_SCHEM		tableSchema
		    TABLE_NAME		tableName
		    COLUMN_NAME		columnName
		    KEY_SEQ		ordinalPosition
		    PK_NAME		constraintName
		} {
		    if {[dict exists $row $odbcKey]} {
			dict set row $tdbcKey [dict get $row $odbcKey]
			dict unset row $odbcKey
		    }
		}
		lappend retval $row
	    }
	    set retval
	} result options]
	catch {rename $stmt {}}
	return -level 0 -options $options $result
    }

    # The 'foreignkeys' method returns a dictionary describing the foreign
    # keys of a table

    method foreignkeys {args} {
	set stmt [::tdbc::odbc::foreignkeysStatement create \
		      Stmt::[incr statementSeq] [self] {*}$args]
       	set status [catch {
	    set fkseq 0
	    set retval {}
	    $stmt foreach -as dicts row {
		foreach {odbcKey tdbcKey} {
		    PKTABLE_CAT		primaryCatalog
		    PKTABLE_SCHEM	primarySchema
		    PKTABLE_NAME	primaryTable
		    PKCOLUMN_NAME	primaryColumn
		    FKTABLE_CAT		foreignCatalog
		    FKTABLE_SCHEM	foreignSchema
		    FKTABLE_NAME	foreignTable
		    FKCOLUMN_NAME	foreignColumn
		    UPDATE_RULE		updateRule
		    DELETE_RULE		deleteRule
		    DEFERRABILITY	deferrable
		    KEY_SEQ		ordinalPosition
		    FK_NAME		foreignConstraintName
		} {
		    if {[dict exists $row $odbcKey]} {
			dict set row $tdbcKey [dict get $row $odbcKey]
			dict unset row $odbcKey
		    }
		}
		# Horrible kludge: If the driver doesn't report FK_NAME,
		# make one up.
		if {![dict exists $row foreignConstraintName]} {
		    if {![dict exists $row ordinalPosition]
			|| [dict get $row ordinalPosition] == 1} {
			set fkname ?[dict get $row foreignTable]?[incr fkseq]
		    }
		    dict set row foreignConstraintName $fkname
		}
		lappend retval $row
	    }
	    set retval
	} result options]
	catch {rename $stmt {}}
	return -level 0 -options $options $result
    }

    # The 'evaldirect' evaluates driver-native SQL code without preparing it,
    # and returns a list of dicts (similar to '$connection allrows -as dicts').

    method evaldirect {sqlStatement} {
	set stmt [::tdbc::odbc::evaldirectStatement create \
		      Stmt::[incr statementSeq] [self] $sqlStatement]
       	set status [catch {
	    $stmt allrows -as dicts
	} result options]
	catch {rename $stmt {}}
	return -level 0 -options $options $result
    }

    # The 'prepareCall' method gives a portable interface to prepare
    # calls to stored procedures.  It delegates to 'prepare' to do the
    # actual work.

    method preparecall {call} {

	regexp {^[[:space:]]*(?:([A-Za-z_][A-Za-z_0-9]*)[[:space:]]*=)?(.*)} \
	    $call -> varName rest
	if {$varName eq {}} {
	    my prepare \\{CALL $rest\\}
	} else {
	    my prepare \\{:$varName=CALL $rest\\}
	}

	if 0 {
	# Kevin thinks this is going to be

	if {![regexp -expanded {
	    ^\s*				   # leading whitespace
	    (?::([[:alpha:]_][[:alnum:]_]*)\s*=\s*) # possible variable name
	    (?:(?:([[:alpha:]_][[:alnum:]_]*)\s*[.]\s*)?   # catalog
	       ([[:alpha:]_][[:alnum:]_]*)\s*[.]\s*)?      # schema
	    ([[:alpha:]_][[:alnum:]_]*)\s*		   # procedure
	    (.*)$					   # argument list
	} $call -> varName catalog schema procedure arglist]} {
	    return -code error \
		-errorCode [list TDBC \
				SYNTAX_ERROR_OR_ACCESS_RULE_VIOLATION \
				42000 ODBC -1] \
		"Syntax error in stored procedure call"
	} else {
	    my PrepareCall $varName $catalog $schema $procedure $arglist
	}

	# at least if making all parameters 'inout' doesn't work.

	}

    }

    # The 'typemap' method returns the type map

    method typemap {} {
	if {![info exists typemap]} {
	    set typemap $::tdbc::odbc::sqltypes
	    set typesStmt [tdbc::odbc::typesStatement new [self]]
	    $typesStmt foreach row {
		set typeNum [dict get $row DATA_TYPE]
		if {![dict exists $typemap $typeNum]} {
		    dict set typemap $typeNum [string tolower \
						   [dict get $row TYPE_NAME]]
		}
		switch -exact -- $typeNum {
		    -9 {
			[self] HasWvarchar 1
		    }
		    -5 {
			[self] HasBigint 1
		    }
		}
	    }
	    rename $typesStmt {}
	}
	return $typemap
    }

    # The 'begintransaction', 'commit' and 'rollback' methods are
    # implemented in C.

}

#-------------------------------------------------------------------------------
#
# tdbc::odbc::statement --
#
#	The class 'tdbc::odbc::statement' models one statement against a
#       database accessed through an ODBC connection
#
#-------------------------------------------------------------------------------

::oo::class create ::tdbc::odbc::statement {

    superclass ::tdbc::statement

    # The constructor is implemented in C. It accepts the handle to
    # the connection and the SQL code for the statement to prepare.
    # It creates a subordinate namespace to hold the statement's
    # active result sets, and then delegates to the 'init' method,
    # written in C, to do the actual work of preparing the statement.

    # The 'resultSetCreate' method forwards to the result set constructor

    forward resultSetCreate ::tdbc::odbc::resultset create

    # The 'params' method describes the parameters to the statement

    method params {} {
	set typemap [[my connection] typemap]
	set result {}
	foreach {name flags typeNum precision scale nullable} [my ParamList] {
	    set lst [dict create \
			 name $name \
			 direction [lindex {unknown in out inout} \
					[expr {($flags & 0x06) >> 1}]] \
			 type [dict get $typemap $typeNum] \
			 precision $precision \
			 scale $scale]
	    if {$nullable in {0 1}} {
		dict set list nullable $nullable
	    }
	    dict set result $name $lst
	}
	return $result
    }

    # Methods implemented in C:
    # init statement ?dictionary?
    #     Does the heavy lifting for the constructor
    # connection
    #	Returns the connection handle to which this statement belongs
    # paramtype paramname ?direction? type ?precision ?scale??
    #     Declares the type of a parameter in the statement

}

#------------------------------------------------------------------------------
#
# tdbc::odbc::tablesStatement --
#
#	The class 'tdbc::odbc::tablesStatement' represents the special
#	statement that queries the tables in a database through an ODBC
#	connection.
#
#------------------------------------------------------------------------------

oo::class create ::tdbc::odbc::tablesStatement {

    superclass ::tdbc::statement

    # The constructor is written in C. It accepts the handle to the
    # connection and a pattern to match table names.  It works in all
    # ways like the constructor of the 'statement' class except that
    # its 'init' method sets up to enumerate tables and not run a SQL
    # query.

    # The 'resultSetCreate' method forwards to the result set constructor

    forward resultSetCreate ::tdbc::odbc::resultset create

}

#------------------------------------------------------------------------------
#
# tdbc::odbc::columnsStatement --
#
#	The class 'tdbc::odbc::tablesStatement' represents the special
#	statement that queries the columns of a table or view
#	in a database through an ODBC connection.
#
#------------------------------------------------------------------------------

oo::class create ::tdbc::odbc::columnsStatement {

    superclass ::tdbc::statement

    # The constructor is written in C. It accepts the handle to the
    # connection, a table name, and a pattern to match column
    # names. It works in all ways like the constructor of the
    # 'statement' class except that its 'init' method sets up to
    # enumerate tables and not run a SQL query.

    # The 'resultSetCreate' class forwards to the constructor of the
    # result set

    forward resultSetCreate ::tdbc::odbc::resultset create

}

#------------------------------------------------------------------------------
#
# tdbc::odbc::primarykeysStatement --
#
#	The class 'tdbc::odbc::primarykeysStatement' represents the special
#	statement that queries the primary keys on a table through an ODBC
#	connection.
#
#------------------------------------------------------------------------------

oo::class create ::tdbc::odbc::primarykeysStatement {

    superclass ::tdbc::statement

    # The constructor is written in C. It accepts the handle to the
    # connection and a table name.  It works in all
    # ways like the constructor of the 'statement' class except that
    # its 'init' method sets up to enumerate primary keys and not run a SQL
    # query.

    # The 'resultSetCreate' method forwards to the result set constructor

    forward resultSetCreate ::tdbc::odbc::resultset create

}

#------------------------------------------------------------------------------
#
# tdbc::odbc::foreignkeysStatement --
#
#	The class 'tdbc::odbc::foreignkeysStatement' represents the special
#	statement that queries the foreign keys on a table through an ODBC
#	connection.
#
#------------------------------------------------------------------------------

oo::class create ::tdbc::odbc::foreignkeysStatement {

    superclass ::tdbc::statement

    # The constructor is written in C. It accepts the handle to the
    # connection and the -primary and -foreign options.  It works in all
    # ways like the constructor of the 'statement' class except that
    # its 'init' method sets up to enumerate foreign keys and not run a SQL
    # query.

    # The 'resultSetCreate' method forwards to the result set constructor

    forward resultSetCreate ::tdbc::odbc::resultset create

}

#------------------------------------------------------------------------------
#
# tdbc::odbc::evaldirectStatement --
#
#	The class 'tdbc::odbc::evaldirectStatement' provides a mechanism to
#	execute driver-name SQL code through an ODBC connection.  The SQL code
#	is not prepared and no tokenization or variable substitution is done.
#
#------------------------------------------------------------------------------

oo::class create ::tdbc::odbc::evaldirectStatement {

    superclass ::tdbc::statement

    # The constructor is written in C. It accepts the handle to the
    # connection and a SQL statement.  It works in all
    # ways like the constructor of the 'statement' class except that
    # its 'init' method does not tokenize or prepare the SQL statement, and
    # sets up to run the SQL query without performing variable substitution.

    # The 'resultSetCreate' method forwards to the result set constructor

    forward resultSetCreate ::tdbc::odbc::resultset create

}

#------------------------------------------------------------------------------
#
# tdbc::odbc::typesStatement --
#
#	The class 'tdbc::odbc::typesStatement' represents the special
#	statement that queries the types available in a database through
#	an ODBC connection.
#
#------------------------------------------------------------------------------


oo::class create ::tdbc::odbc::typesStatement {

    superclass ::tdbc::statement

    # The constructor is written in C. It accepts the handle to the
    # connection, and (optionally) a data type number. It works in all
    # ways like the constructor of the 'statement' class except that
    # its 'init' method sets up to enumerate types and not run a SQL
    # query.

    # The 'resultSetCreate' method forwards to the constructor of result sets

    forward resultSetCreate ::tdbc::odbc::resultset create

    # The C code contains a variant implementation of the 'init' method.

}

#------------------------------------------------------------------------------
#
# tdbc::odbc::resultset --
#
#	The class 'tdbc::odbc::resultset' models the result set that is
#	produced by executing a statement against an ODBC database.
#
#------------------------------------------------------------------------------

::oo::class create ::tdbc::odbc::resultset {

    superclass ::tdbc::resultset

    # Methods implemented in C include:

    # constructor statement ?dictionary?
    #     -- Executes the statement against the database, optionally providing
    #        a dictionary of substituted parameters (default is to get params
    #        from variables in the caller's scope).
    # columns
    #     -- Returns a list of the names of the columns in the result.
    # nextdict
    #     -- Stores the next row of the result set in the given variable in
    #        the caller's scope as a dictionary whose keys are
    #        column names and whose values are column values.
    # nextlist
    #     -- Stores the next row of the result set in the given variable in
    #        the caller's scope as a list of cells.
    # rowcount
    #     -- Returns a count of rows affected by the statement, or -1
    #        if the count of rows has not been determined.

}
