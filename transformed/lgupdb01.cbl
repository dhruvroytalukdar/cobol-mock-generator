       PROCESS SQL
      ******************************************************************
      *                                                                *
      * (C) Copyright IBM Corp. 2011, 2021                             *
      *                                                                *
      *                     UPDATE policy details                      *
      *                                                                *
      ******************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LGUPDB01.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
      *
       DATA DIVISION.

       WORKING-STORAGE SECTION.

      *----------------------------------------------------------------*
      * Common defintions                                              *
      *----------------------------------------------------------------*
      * Run time (debug) infomation for this invocation
        01  WS-HEADER.
           03 WS-EYECATCHER            PIC X(16)
                                        VALUE 'LGUPDB01------WS'.
           03 WS-TRANSID               PIC X(4).
           03 WS-TERMID                PIC X(4).
           03 WS-TASKNUM               PIC 9(7).
           03 WS-FILLER                PIC X.
           03 WS-ADDR-DFHCOMMAREA      USAGE is POINTER.
           03 WS-CALEN                 PIC S9(4) COMP.
           03 WS-RETRY                 PIC X.

      * Variables for time/date processing
       01  WS-ABSTIME                  PIC S9(8) COMP VALUE +0.
       01  WS-TIME                     PIC X(8)  VALUE SPACES.
       01  WS-DATE                     PIC X(10) VALUE SPACES.

      * Error Message structure
       01  ERROR-MSG.
           03 EM-DATE                  PIC X(8)  VALUE SPACES.
           03 FILLER                   PIC X     VALUE SPACES.
           03 EM-TIME                  PIC X(6)  VALUE SPACES.
           03 FILLER                   PIC X(9)  VALUE ' LGUPDB01'.
           03 EM-VARIABLE.
             05 FILLER                 PIC X(6)  VALUE ' CNUM='.
             05 EM-CUSNUM              PIC X(10)  VALUE SPACES.
             05 FILLER                 PIC X(6)  VALUE ' PNUM='.
             05 EM-POLNUM              PIC X(10)  VALUE SPACES.
             05 EM-SQLREQ              PIC X(16) VALUE SPACES.
             05 FILLER                 PIC X(9)  VALUE ' SQLCODE='.
             05 EM-SQLRC               PIC +9(5) USAGE DISPLAY.

       01  CA-ERROR-MSG.
           03 FILLER                   PIC X(9)  VALUE 'COMMAREA='.
           03 CA-DATA                  PIC X(90) VALUE SPACES.
      *----------------------------------------------------------------*

      *----------------------------------------------------------------*
      * Definitions required for data manipulation                     *
      *----------------------------------------------------------------*
      * Fields to be used to calculate minimum commarea length required
      * (for Endowment this does not allow for VARCHAR)
       01  WS-COMMAREA-LENGTHS.
           03 WS-CA-HEADER-LEN         PIC S9(4) COMP VALUE +28.
           03 WS-REQUIRED-CA-LEN       PIC S9(4) COMP VALUE +0.

      * Define a WS-VARYing length character string to contain actual
      * amount of data that will be updated in Varchar field
       01 WS-VARY-FIELD.
          49 WS-VARY-LEN               PIC S9(4) COMP.
          49 WS-VARY-CHAR              PIC X(3900).

      *----------------------------------------------------------------*

      *----------------------------------------------------------------*
      * Definitions required by SQL statement                          *
      *   DB2 datatypes to COBOL equivalents                           *
      *     SMALLINT    :   PIC S9(4) COMP                             *
      *     INTEGER     :   PIC S9(9) COMP                             *
      *     DATE        :   PIC X(10)                                  *
      *     TIMESTAMP   :   PIC X(26)                                  *
      *----------------------------------------------------------------*
      * Host variables for input to DB2 integer types
      * Any values specified in SQL stmts must be defined here so
      * available to SQL pre-compiler
       01 DB2-IN-INTEGERS.
          03 DB2-CUSTOMERNUM-INT       PIC S9(9) COMP.
          03 DB2-POLICYNUM-INT         PIC S9(9) COMP.
          03 DB2-BROKERID-INT          PIC S9(9) COMP.
          03 DB2-PAYMENT-INT           PIC S9(9) COMP.
          03 DB2-E-TERM-SINT           PIC S9(4) COMP.
          03 DB2-E-SUMASSURED-INT      PIC S9(9) COMP.
          03 DB2-H-BEDROOMS-SINT       PIC S9(4) COMP.
          03 DB2-H-VALUE-INT           PIC S9(9) COMP.
          03 DB2-M-VALUE-INT           PIC S9(9) COMP.
          03 DB2-M-CC-SINT             PIC S9(4) COMP.
          03 DB2-M-PREMIUM-INT         PIC S9(9) COMP.
          03 DB2-M-ACCIDENTS-INT       PIC S9(9) COMP.

      *  Host variables to store result of DB2 Fetch
      *  Must be an SQL INCLUDE so available to SQL pre-compiler
      * >>> BEGIN EXEC_SQL_INCLUDE LGPOLICY (LGPOLICY.cpy)
      ******************************************************************
      *                                                                *
      * (C) Copyright IBM Corp. 2011, 2020                             *
      *                                                                *
      ******************************************************************
      *               COPYBOOK for Policy details                      *
      *                                                                *
      *   Structures to map values obtained from DB2 tables:           *
      *   Customer, Policy, Endowment, House and Motor.                *
      *                                                                *
      *   All lengths of policy fields will be defined here so that    *
      *   if any of the DB2 table contents change the lengths will     *
      *   only need to be changed here.                                *
      *                                                                *
      ******************************************************************
       01  WS-POLICY-LENGTHS.
           03 WS-CUSTOMER-LEN          PIC S9(4) COMP VALUE +72.
           03 WS-POLICY-LEN            PIC S9(4) COMP VALUE +72.
           03 WS-ENDOW-LEN             PIC S9(4) COMP VALUE +52.
           03 WS-HOUSE-LEN             PIC S9(4) COMP VALUE +58.
           03 WS-MOTOR-LEN             PIC S9(4) COMP VALUE +65.
           03 WS-COMM-LEN              PIC S9(4) COMP VALUE +1102.
           03 WS-CLAIM-LEN             PIC S9(4) COMP VALUE +546.
           03 WS-FULL-ENDOW-LEN        PIC S9(4) COMP VALUE +124.
           03 WS-FULL-HOUSE-LEN        PIC S9(4) COMP VALUE +130.
           03 WS-FULL-MOTOR-LEN        PIC S9(4) COMP VALUE +137.
           03 WS-FULL-COMM-LEN         PIC S9(4) COMP VALUE +1174.
           03 WS-FULL-CLAIM-LEN        PIC S9(4) COMP VALUE +618.
           03 WS-SUMRY-ENDOW-LEN       PIC S9(4) COMP VALUE +25.

       01  DB2-CUSTOMER.
           03 DB2-FIRSTNAME            PIC X(10).
           03 DB2-LASTNAME             PIC X(20).
           03 DB2-DATEOFBIRTH          PIC X(10).
           03 DB2-HOUSENAME            PIC X(20).
           03 DB2-HOUSENUMBER          PIC X(4).
           03 DB2-POSTCODE             PIC X(8).
           03 DB2-PHONE-MOBILE         PIC X(20).
           03 DB2-PHONE-HOME           PIC X(20).
           03 DB2-EMAIL-ADDRESS        PIC X(100).

       01  DB2-POLICY.
           03 DB2-POLICYTYPE           PIC X.
           03 DB2-POLICYNUMBER         PIC 9(10).
           03 DB2-POLICY-COMMON.
              05 DB2-ISSUEDATE         PIC X(10).
              05 DB2-EXPIRYDATE        PIC X(10).
              05 DB2-LASTCHANGED       PIC X(26).
              05 DB2-BROKERID          PIC 9(10).
              05 DB2-BROKERSREF        PIC X(10).
              05 DB2-PAYMENT           PIC 9(6).

       01  DB2-ENDOWMENT.
           03 DB2-ENDOW-FIXED.
              05 DB2-E-WITHPROFITS      PIC X.
              05 DB2-E-EQUITIES         PIC X.
              05 DB2-E-MANAGEDFUND      PIC X.
              05 DB2-E-FUNDNAME         PIC X(10).
              05 DB2-E-TERM             PIC 9(2).
              05 DB2-E-SUMASSURED       PIC 9(6).
              05 DB2-E-LIFEASSURED      PIC X(31).
           03 DB2-E-PADDINGDATA         PIC X(32611).

       01  DB2-HOUSE.
           03 DB2-H-PROPERTYTYPE       PIC X(15).
           03 DB2-H-BEDROOMS           PIC 9(3).
           03 DB2-H-VALUE              PIC 9(8).
           03 DB2-H-HOUSENAME          PIC X(20).
           03 DB2-H-HOUSENUMBER        PIC X(4).
           03 DB2-H-POSTCODE           PIC X(8).

       01  DB2-MOTOR.
           03 DB2-M-MAKE               PIC X(15).
           03 DB2-M-MODEL              PIC X(15).
           03 DB2-M-VALUE              PIC 9(6).
           03 DB2-M-REGNUMBER          PIC X(7).
           03 DB2-M-COLOUR             PIC X(8).
           03 DB2-M-CC                 PIC 9(4).
           03 DB2-M-MANUFACTURED       PIC X(10).
           03 DB2-M-PREMIUM            PIC 9(6).
           03 DB2-M-ACCIDENTS          PIC 9(6).

       01  DB2-COMMERCIAL.
           03 DB2-B-Address            PIC X(255).
           03 DB2-B-Postcode           PIC X(8).
           03 DB2-B-Latitude           PIC X(11).
           03 DB2-B-Longitude          PIC X(11).
           03 DB2-B-Customer           PIC X(255).
           03 DB2-B-PropType           PIC X(255).
           03 DB2-B-FirePeril          PIC 9(4).
           03 DB2-B-FirePremium        PIC 9(8).
           03 DB2-B-CrimePeril         PIC 9(4).
           03 DB2-B-CrimePremium       PIC 9(8).
           03 DB2-B-FloodPeril         PIC 9(4).
           03 DB2-B-FloodPremium       PIC 9(8).
           03 DB2-B-WeatherPeril       PIC 9(4).
           03 DB2-B-WeatherPremium     PIC 9(8).
           03 DB2-B-Status             PIC 9(4).
           03 DB2-B-RejectReason       PIC X(255).

       01  DB2-CLAIM.
           03 DB2-C-Num                PIC 9(10).
           03 DB2-C-Date               PIC X(10).
           03 DB2-C-Paid               PIC 9(8).
           03 DB2-C-Value              PIC 9(8).
           03 DB2-C-Cause              PIC X(255).
           03 DB2-C-Observations       PIC X(255).
      * <<< END EXEC_SQL_INCLUDE LGPOLICY

      * Indicator variables for columns which could return nulls
      *   if these are not specified and SQL FETCH tries to return
      *   null value for a listed column it will FAIL with SQLCODE=
       77  IND-BROKERID                PIC S9(4) COMP.
       77  IND-BROKERSREF              PIC S9(4) COMP.
       77  IND-PAYMENT                 PIC S9(4) COMP.
       77  LGUPVS01                    Pic X(8) value 'LGUPVS01'.
      *----------------------------------------------------------------*

      *----------------------------------------------------------------*
      *    DB2 CONTROL
      *----------------------------------------------------------------*
      * SQLCA DB2 communications area
      * >>> BEGIN EXEC_SQL_INCLUDE SQLCA (<builtin:SQLCA>)
      *****************************************************************
      * SQLCA - DB2 SQL communication area (standard layout).         *
      * Supplied by cobol_transformer: DB2 provides this at precompile*
      * time on z/OS, so no copybook file exists in the source tree.  *
      *****************************************************************
       01  SQLCA.
           05  SQLCAID            PIC X(8).
           05  SQLCABC            PIC S9(9) COMP-5.
           05  SQLCODE            PIC S9(9) COMP-5.
           05  SQLERRM.
               49  SQLERRML       PIC S9(4) COMP-5.
               49  SQLERRMC       PIC X(70).
           05  SQLERRP            PIC X(8).
           05  SQLERRD            OCCURS 6 TIMES
                                  PIC S9(9) COMP-5.
           05  SQLWARN.
               10  SQLWARN0       PIC X.
               10  SQLWARN1       PIC X.
               10  SQLWARN2       PIC X.
               10  SQLWARN3       PIC X.
               10  SQLWARN4       PIC X.
               10  SQLWARN5       PIC X.
               10  SQLWARN6       PIC X.
               10  SQLWARN7       PIC X.
               10  SQLWARN8       PIC X.
               10  SQLWARN9       PIC X.
               10  SQLWARNA       PIC X.
           05  SQLSTATE           PIC X(5).
      * <<< END EXEC_SQL_INCLUDE SQLCA

      *----------------------------------------------------------------*
      * Declare Cursors
      *----------------------------------------------------------------*
      * Cursor to select details from policy table (with lock)
      * will NOT update payment or commission fields
      *    EXEC SQL
      *      DECLARE POLICY_CURSOR CURSOR WITH HOLD FOR
      *        SELECT ISSUEDATE,
      *               EXPIRYDATE,
      *               LASTCHANGED,
      *               BROKERID,
      *               BROKERSREFERENCE
      *        FROM POLICY
      *        WHERE ( CUSTOMERNUMBER = :DB2-CUSTOMERNUM-INT AND
      *                POLICYNUMBER = :DB2-POLICYNUM-INT )
      *        FOR UPDATE OF ISSUEDATE,
      *                      EXPIRYDATE,
      *                      LASTCHANGED,
      *                      BROKERID,
      *                      BROKERSREFERENCE
      *    END-EXEC.

      ******************************************************************
      *    L I N K A G E     S E C T I O N
      ******************************************************************
      * >>> LINKAGE SECTION promoted to WORKING-STORAGE by cobol_transformer:
      * >>> no CICS caller supplies a commarea, so these items need storage.
      *LINKAGE SECTION.

       01  DFHCOMMAREA.
      * >>> BEGIN EXEC_SQL_INCLUDE LGCMAREA (LGCMAREA.cpy)
      ******************************************************************
      *                                                                *
      * (C) Copyright IBM Corp. 2011, 2020                             *
      *                                                                *
      *               COPYBOOK for COMMAREA structure                  *
      *                                                                *
      *   This commarea can be used for all functions                  *
      *                                                                *
      ******************************************************************
           03 CA-REQUEST-ID            PIC X(6).
           03 CA-RETURN-CODE           PIC 9(2).
           03 CA-CUSTOMER-NUM          PIC 9(10).
           03 CA-REQUEST-SPECIFIC      PIC X(32482).
      *    Fields used in INQ All and ADD customer
           03 CA-CUSTOMER-REQUEST REDEFINES CA-REQUEST-SPECIFIC.
              05 CA-FIRST-NAME         PIC X(10).
              05 CA-LAST-NAME          PIC X(20).
              05 CA-DOB                PIC X(10).
              05 CA-HOUSE-NAME         PIC X(20).
              05 CA-HOUSE-NUM          PIC X(4).
              05 CA-POSTCODE           PIC X(8).
              05 CA-NUM-POLICIES       PIC 9(3).
              05 CA-PHONE-MOBILE       PIC X(20).
              05 CA-PHONE-HOME         PIC X(20).
              05 CA-EMAIL-ADDRESS      PIC X(100).
              05 CA-POLICY-DATA        PIC X(32267).
      *    Fields used in Customer security call
           03 CA-CUSTSECR-REQUEST REDEFINES CA-REQUEST-SPECIFIC.
              05 CA-CUSTSECR-PASS      PIC X(32).
              05 CA-CUSTSECR-COUNT     PIC X(4).
              05 CA-CUSTSECR-STATE     PIC X.
              05 CA-CUSTSECR-DATA      PIC X(32445).
      *    Fields used in INQ, UPD, ADD & DELETE policy
           03 CA-POLICY-REQUEST REDEFINES CA-REQUEST-SPECIFIC.
              05 CA-POLICY-NUM         PIC 9(10).
      *       Common policy details
              05 CA-POLICY-COMMON.
                 07 CA-ISSUE-DATE      PIC X(10).
                 07 CA-EXPIRY-DATE     PIC X(10).
                 07 CA-LASTCHANGED     PIC X(26).
                 07 CA-BROKERID        PIC 9(10).
                 07 CA-BROKERSREF      PIC X(10).
                 07 CA-PAYMENT         PIC 9(6).
              05 CA-POLICY-SPECIFIC    PIC X(32400).
      *       Endowment policy description
              05 CA-ENDOWMENT REDEFINES CA-POLICY-SPECIFIC.
                 07 CA-E-WITH-PROFITS    PIC X.
                 07 CA-E-EQUITIES        PIC X.
                 07 CA-E-MANAGED-FUND    PIC X.
                 07 CA-E-FUND-NAME       PIC X(10).
                 07 CA-E-TERM            PIC 99.
                 07 CA-E-SUM-ASSURED     PIC 9(6).
                 07 CA-E-LIFE-ASSURED    PIC X(31).
                 07 CA-E-PADDING-DATA    PIC X(32348).
      *       House policy description
              05 CA-HOUSE REDEFINES CA-POLICY-SPECIFIC.
                 07 CA-H-PROPERTY-TYPE   PIC X(15).
                 07 CA-H-BEDROOMS        PIC 9(3).
                 07 CA-H-VALUE           PIC 9(8).
                 07 CA-H-HOUSE-NAME      PIC X(20).
                 07 CA-H-HOUSE-NUMBER    PIC X(4).
                 07 CA-H-POSTCODE        PIC X(8).
                 07 CA-H-FILLER          PIC X(32342).
      *       Motor policy description
              05 CA-MOTOR REDEFINES CA-POLICY-SPECIFIC.
                 07 CA-M-MAKE            PIC X(15).
                 07 CA-M-MODEL           PIC X(15).
                 07 CA-M-VALUE           PIC 9(6).
                 07 CA-M-REGNUMBER       PIC X(7).
                 07 CA-M-COLOUR          PIC X(8).
                 07 CA-M-CC              PIC 9(4).
                 07 CA-M-MANUFACTURED    PIC X(10).
                 07 CA-M-PREMIUM         PIC 9(6).
                 07 CA-M-ACCIDENTS       PIC 9(6).
                 07 CA-M-FILLER          PIC X(32323).
      *       Commercial policy description
              05 CA-COMMERCIAL REDEFINES CA-POLICY-SPECIFIC.
                 07 CA-B-Address         PIC X(255).
                 07 CA-B-Postcode        PIC X(8).
                 07 CA-B-Latitude        PIC X(11).
                 07 CA-B-Longitude       PIC X(11).
                 07 CA-B-Customer        PIC X(255).
                 07 CA-B-PropType        PIC X(255).
                 07 CA-B-FirePeril       PIC 9(4).
                 07 CA-B-FirePremium     PIC 9(8).
                 07 CA-B-CrimePeril      PIC 9(4).
                 07 CA-B-CrimePremium    PIC 9(8).
                 07 CA-B-FloodPeril      PIC 9(4).
                 07 CA-B-FloodPremium    PIC 9(8).
                 07 CA-B-WeatherPeril    PIC 9(4).
                 07 CA-B-WeatherPremium  PIC 9(8).
                 07 CA-B-Status          PIC 9(4).
                 07 CA-B-RejectReason    PIC X(255).
                 07 CA-B-FILLER          PIC X(31298).
      *       CLAIM policy description
              05 CA-CLAIM      REDEFINES CA-POLICY-SPECIFIC.
                 07 CA-C-Num             PIC 9(10).
                 07 CA-C-Date            PIC X(10).
                 07 CA-C-Paid            PIC 9(8).
                 07 CA-C-Value           PIC 9(8).
                 07 CA-C-Cause           PIC X(255).
                 07 CA-C-Observations    PIC X(255).
                 07 CA-C-FILLER          PIC X(31854).
      * <<< END EXEC_SQL_INCLUDE LGCMAREA


      ******************************************************************
      *    P R O C E D U R E S
      ******************************************************************
      * >>> TOOL-GENERATED MOCK SUPPORT FIELDS <<<
       01  EIBTRNID     PIC X(4) VALUE 'GENA'.
       01  EIBTASKN     PIC S9(7) COMP-3 VALUE 1.
       01  EIBTRMID     PIC X(4) VALUE 'TRM1'.
       01  EIBCALEN     PIC S9(4) COMP VALUE 9999.
       01  MOCK-FETCH-CNT-4       PIC S9(9) COMP VALUE 0.
       PROCEDURE DIVISION.

      *----------------------------------------------------------------*
       MAINLINE SECTION.

      *----------------------------------------------------------------*
      * Common code                                                    *
      *----------------------------------------------------------------*
      * initialize working storage variables
           INITIALIZE WS-HEADER.
      * set up general variable
           MOVE EIBTRNID TO WS-TRANSID.
           MOVE EIBTRMID TO WS-TERMID.
           MOVE EIBTASKN TO WS-TASKNUM.
           MOVE SPACES   TO WS-RETRY.
      *----------------------------------------------------------------*
      * initialize DB2 host variables
           INITIALIZE DB2-POLICY.
           INITIALIZE DB2-IN-INTEGERS.

      *----------------------------------------------------------------*
      * Check commarea and obtain required details                     *
      *----------------------------------------------------------------*
      * If NO commarea received issue an ABEND
           IF EIBCALEN IS EQUAL TO ZERO
               MOVE ' NO COMMAREA RECEIVED' TO EM-VARIABLE
               PERFORM WRITE-ERROR-MESSAGE
      *        EXEC CICS ABEND ABCODE('LGCA') NODUMP END-EXEC
               DISPLAY '>>> MOCK ABEND @MAINLINE: ' 'ABCODE=LGCA'
               GOBACK
           END-IF

      * initialize commarea return code to zero
           MOVE '00' TO CA-RETURN-CODE
           MOVE EIBCALEN TO WS-CALEN.
           SET WS-ADDR-DFHCOMMAREA TO ADDRESS OF DFHCOMMAREA.

      * Convert commarea customer & policy nums to DB2 integer format
           MOVE CA-CUSTOMER-NUM TO DB2-CUSTOMERNUM-INT
           MOVE CA-POLICY-NUM   TO DB2-POLICYNUM-INT
      * and save in error msg field incase required
           MOVE CA-CUSTOMER-NUM TO EM-CUSNUM
           MOVE CA-POLICY-NUM   TO EM-POLNUM

      *----------------------------------------------------------------*
      * Check which policy type is being requested                     *
      *   and check commarea length                                    *
      *----------------------------------------------------------------*

      *    Call procedure to update required tables
           PERFORM UPDATE-POLICY-DB2-INFO.

      *    EXEC CICS LINK Program(LGUPVS01)
      *         Commarea(DFHCOMMAREA)
      *         LENGTH(225)
      *    END-EXEC.
           DISPLAY '>>> MOCK LINK @MAINLINE: ' 'LGUPVS01'.

      * Return to caller
       END-PROGRAM.
      *    EXEC CICS RETURN END-EXEC.
           DISPLAY '>>> MOCK RETURN @END-PROGRAM'
           GOBACK.

       MAINLINE-EXIT.
           EXIT.
      *----------------------------------------------------------------*

      *================================================================*
      * Fetch a row from Policy tables using POLICY-CURSOR             *
      *   Host variables specified on INTO statement must correspond   *
      *   in order and size to columns specified on SELECT statement   *
      *   in CURSOR defintion.                                         *
      *================================================================*
       FETCH-DB2-POLICY-ROW.
           MOVE ' FETCH  ROW   ' TO EM-SQLREQ
      *    EXEC SQL
      *      FETCH POLICY_CURSOR
      *      INTO  :DB2-ISSUEDATE,
      *            :DB2-EXPIRYDATE,
      *            :DB2-LASTCHANGED,
      *            :DB2-BROKERID-INT INDICATOR :IND-BROKERID,
      *            :DB2-BROKERSREF INDICATOR :IND-BROKERSREF,
      *            :DB2-PAYMENT-INT INDICATOR :IND-PAYMENT
      *    END-EXEC
           DISPLAY '>>> MOCK FETCH @FETCH-DB2-POLICY-ROW: '
               'POLICY_CURSOR'
           ADD 1 TO MOCK-FETCH-CNT-4
           IF MOCK-FETCH-CNT-4 > 1 MOVE 100 TO SQLCODE ELSE MOVE 0 TO
               SQLCODE MOVE '2024-01-01' TO DB2-ISSUEDATE MOVE
               '2024-01-01' TO DB2-EXPIRYDATE MOVE 'DUMMY' TO
               DB2-LASTCHANGED MOVE 1 TO DB2-BROKERID-INT MOVE 0 TO
               IND-BROKERID MOVE 'DUMMY' TO DB2-BROKERSREF MOVE 0 TO
               IND-BROKERSREF MOVE 0 TO DB2-PAYMENT-INT MOVE 0 TO
               IND-PAYMENT END-IF
           EXIT.

      *================================================================*
      * 1) Use SELECT FOR UPDATE to obtain a lock on the row in the    *
      *    policy table, check that Timestamp in database matches that *
      *    received in commarea:                                       *
      * 2a) if not: unlock DB2 record, abandon update & return to user *
      * 2b) if match: update policy specific table with data from      *
      *     commarea                                                   *
      * 3) update policy table with data from commarea and new         *
      *    timestamp (which releases row lock on policy table)         *
      *================================================================*
       UPDATE-POLICY-DB2-INFO.

      *    Open the cursor.
           MOVE ' OPEN   PCURSOR ' TO EM-SQLREQ
      *    EXEC SQL
      *      OPEN POLICY_CURSOR
      *    END-EXEC
           DISPLAY '>>> MOCK OPEN @UPDATE-POLICY-DB2-INFO: '
               'POLICY_CURSOR'
           MOVE 0 TO SQLCODE

           Evaluate SQLCODE
             When 0
               MOVE '00' TO CA-RETURN-CODE
             When -913
               MOVE '90' TO CA-RETURN-CODE
               PERFORM WRITE-ERROR-MESSAGE
      *        EXEC CICS RETURN END-EXEC
               DISPLAY '>>> MOCK RETURN @UPDATE-POLICY-DB2-INFO'
               GOBACK
             When Other
               MOVE '90' TO CA-RETURN-CODE
               PERFORM WRITE-ERROR-MESSAGE
      *        EXEC CICS RETURN END-EXEC
               DISPLAY '>>> MOCK RETURN @UPDATE-POLICY-DB2-INFO'
               GOBACK
           END-Evaluate.

      *    Fetch the first row (we only expect one matching row)
           PERFORM FETCH-DB2-POLICY-ROW

           IF SQLCODE = 0
      *      Fetch was successful
      *      Compare timestamp in commarea with that in DB2
             IF CA-LASTCHANGED EQUAL TO DB2-LASTCHANGED

      *----------------------------------------------------------------*
      *      Select for Update and Update specific policy type table   *
      *----------------------------------------------------------------*
             EVALUATE CA-REQUEST-ID

      *** Endowment ***
               WHEN '01UEND'
      *          Call routine to update Endowment table
                 PERFORM UPDATE-ENDOW-DB2-INFO

      *** House ***
               WHEN '01UHOU'
      *          Call routine to update Housetable
                 PERFORM UPDATE-HOUSE-DB2-INFO

      *** Motor ***
               WHEN '01UMOT'
      *          Call routine to update Motor table
                 PERFORM UPDATE-MOTOR-DB2-INFO

             END-EVALUATE
      *----------------------------------------------------------------*
              IF CA-RETURN-CODE NOT EQUAL '00'
      *         Update policy type specific table has failed
      *         So close cursor and return
                PERFORM CLOSE-PCURSOR
      *         EXEC CICS RETURN END-EXEC
                DISPLAY '>>> MOCK RETURN @UPDATE-POLICY-DB2-INFO'
                GOBACK
              END-IF

      *----------------------------------------------------------------*
      *        Now update Policy table and set new timestamp           *
      *----------------------------------------------------------------*
      *        Move numeric commarea fields to integer format
               MOVE CA-BROKERID      TO DB2-BROKERID-INT
               MOVE CA-PAYMENT       TO DB2-PAYMENT-INT

      *        Update policy table details
               MOVE ' UPDATE POLICY  ' TO EM-SQLREQ
      *        EXEC SQL
      *          UPDATE POLICY
      *            SET ISSUEDATE        = :CA-ISSUE-DATE,
      *                EXPIRYDATE       = :CA-EXPIRY-DATE,
      *                LASTCHANGED      = CURRENT TIMESTAMP ,
      *                BROKERID         = :DB2-BROKERID-INT,
      *                BROKERSREFERENCE = :CA-BROKERSREF
      *            WHERE CURRENT OF POLICY_CURSOR
      *        END-EXEC
               DISPLAY '>>> MOCK UPDATE @UPDATE-POLICY-DB2-INFO: '
                   'TABLE=POLICY'
               MOVE 0 TO SQLCODE

      *        get value of assigned Timestamp for return in commarea
      *        EXEC SQL
      *          SELECT LASTCHANGED
      *            INTO :CA-LASTCHANGED
      *            FROM POLICY
      *            WHERE POLICYNUMBER = :DB2-POLICYNUM-INT
      *        END-EXEC
               DISPLAY '>>> MOCK SELECT @UPDATE-POLICY-DB2-INFO: '
                   'TABLE=POLICY'
               MOVE 'DUMMY' TO CA-LASTCHANGED
               MOVE 0 TO SQLCODE

               IF SQLCODE NOT EQUAL 0
      *          Non-zero SQLCODE from Update of policy table
      *            EXEC CICS SYNCPOINT ROLLBACK END-EXEC
                   DISPLAY '>>> MOCK SYNCPOINT @UPDATE-POLICY-DB2-INFO'
                   MOVE '90' TO CA-RETURN-CODE
      *            Write error message to TD QUEUE(CSMT)
                   PERFORM WRITE-ERROR-MESSAGE
               END-IF

             ELSE
      *        Timestamps do not match (policy table v commarea)
               MOVE '02' TO CA-RETURN-CODE
             END-IF

           ELSE
      *      Non-zero SQLCODE from first SQL FETCH statement
             IF SQLCODE EQUAL 100
               MOVE '01' TO CA-RETURN-CODE
             ELSE
               MOVE '90' TO CA-RETURN-CODE
      *        Write error message to TD QUEUE(CSMT)
               PERFORM WRITE-ERROR-MESSAGE
             END-IF
           END-IF.
      *    Now close the Cursor and we're done!
           PERFORM CLOSE-PCURSOR.

       CLOSE-PCURSOR.
      *    Now close the Cursor and we're done!
           MOVE ' CLOSE  PCURSOR' TO EM-SQLREQ
      *    EXEC SQL
      *      CLOSE POLICY_CURSOR
      *    END-EXEC.
           DISPLAY '>>> MOCK CLOSE @CLOSE-PCURSOR: ' 'POLICY_CURSOR'
           MOVE 0 TO SQLCODE.

           Evaluate SQLCODE
             When 0
               MOVE '00' TO CA-RETURN-CODE
             When -501
               MOVE '00' TO CA-RETURN-CODE
               MOVE '-501 detected c' TO EM-SQLREQ
      *        EXEC CICS RETURN END-EXEC
               DISPLAY '>>> MOCK RETURN @CLOSE-PCURSOR'
               GOBACK
             When Other
               MOVE '90' TO CA-RETURN-CODE
               PERFORM WRITE-ERROR-MESSAGE
      *        EXEC CICS RETURN END-EXEC
               DISPLAY '>>> MOCK RETURN @CLOSE-PCURSOR'
               GOBACK
           END-Evaluate.
           EXIT.

      *================================================================*
      * Update row in Endowment table which matches customer and       *
      * policy number requested.                                       *
      *================================================================*
       UPDATE-ENDOW-DB2-INFO.

      *    Move numeric commarea fields to DB2 Integer formats
           MOVE CA-E-TERM        TO DB2-E-TERM-SINT
           MOVE CA-E-SUM-ASSURED TO DB2-E-SUMASSURED-INT

           MOVE ' UPDATE ENDOW ' TO EM-SQLREQ
      *    EXEC SQL
      *      UPDATE ENDOWMENT
      *        SET
      *          WITHPROFITS   = :CA-E-WITH-PROFITS,
      *            EQUITIES    = :CA-E-EQUITIES,
      *            MANAGEDFUND = :CA-E-MANAGED-FUND,
      *            FUNDNAME    = :CA-E-FUND-NAME,
      *            TERM        = :DB2-E-TERM-SINT,
      *            SUMASSURED  = :DB2-E-SUMASSURED-INT,
      *            LIFEASSURED = :CA-E-LIFE-ASSURED
      *        WHERE
      *            POLICYNUMBER = :DB2-POLICYNUM-INT
      *    END-EXEC
           DISPLAY '>>> MOCK UPDATE @UPDATE-ENDOW-DB2-INFO: '
               'TABLE=ENDOWMENT'
           MOVE 0 TO SQLCODE

           IF SQLCODE NOT EQUAL 0
      *      Non-zero SQLCODE from UPDATE statement
             IF SQLCODE EQUAL 100
               MOVE '01' TO CA-RETURN-CODE
             ELSE
               MOVE '90' TO CA-RETURN-CODE
      *        Write error message to TD QUEUE(CSMT)
               PERFORM WRITE-ERROR-MESSAGE
             END-IF
           END-IF.
           EXIT.

      *================================================================*
      * Update row in House table which matches customer and           *
      * policy number requested.                                       *
      *================================================================*
       UPDATE-HOUSE-DB2-INFO.

      *    Move numeric commarea fields to DB2 Integer formats
           MOVE CA-H-BEDROOMS    TO DB2-H-BEDROOMS-SINT
           MOVE CA-H-VALUE       TO DB2-H-VALUE-INT

           MOVE ' UPDATE HOUSE ' TO EM-SQLREQ
      *    EXEC SQL
      *      UPDATE HOUSE
      *        SET
      *             PROPERTYTYPE = :CA-H-PROPERTY-TYPE,
      *             BEDROOMS     = :DB2-H-BEDROOMS-SINT,
      *             VALUE        = :DB2-H-VALUE-INT,
      *             HOUSENAME    = :CA-H-HOUSE-NAME,
      *             HOUSENUMBER  = :CA-H-HOUSE-NUMBER,
      *             POSTCODE     = :CA-H-POSTCODE
      *        WHERE
      *             POLICYNUMBER = :DB2-POLICYNUM-INT
      *    END-EXEC
           DISPLAY '>>> MOCK UPDATE @UPDATE-HOUSE-DB2-INFO: '
               'TABLE=HOUSE'
           MOVE 0 TO SQLCODE

           IF SQLCODE NOT EQUAL 0
      *      Non-zero SQLCODE from UPDATE statement
             IF SQLCODE = 100
               MOVE '01' TO CA-RETURN-CODE
             ELSE
               MOVE '90' TO CA-RETURN-CODE
      *        Write error message to TD QUEUE(CSMT)
               PERFORM WRITE-ERROR-MESSAGE
             END-IF
           END-IF.
           EXIT.

      *================================================================*
      * Update row in Motor table which matches customer and           *
      * policy number requested.                                       *
      *================================================================*
       UPDATE-MOTOR-DB2-INFO.

      *    Move numeric commarea fields to DB2 Integer formats
           MOVE CA-M-CC          TO DB2-M-CC-SINT
           MOVE CA-M-VALUE       TO DB2-M-VALUE-INT
           MOVE CA-M-PREMIUM     TO DB2-M-PREMIUM-INT
           MOVE CA-M-ACCIDENTS   TO DB2-M-ACCIDENTS-INT

           MOVE ' UPDATE MOTOR ' TO EM-SQLREQ
      *    EXEC SQL
      *      UPDATE MOTOR
      *        SET
      *             MAKE              = :CA-M-MAKE,
      *             MODEL             = :CA-M-MODEL,
      *             VALUE             = :DB2-M-VALUE-INT,
      *             REGNUMBER         = :CA-M-REGNUMBER,
      *             COLOUR            = :CA-M-COLOUR,
      *             CC                = :DB2-M-CC-SINT,
      *             YEAROFMANUFACTURE = :CA-M-MANUFACTURED,
      *             PREMIUM           = :DB2-M-PREMIUM-INT,
      *             ACCIDENTS         = :DB2-M-ACCIDENTS-INT
      *        WHERE
      *             POLICYNUMBER      = :DB2-POLICYNUM-INT
      *    END-EXEC
           DISPLAY '>>> MOCK UPDATE @UPDATE-MOTOR-DB2-INFO: '
               'TABLE=MOTOR'
           MOVE 0 TO SQLCODE

           IF SQLCODE NOT EQUAL 0
      *      Non-zero SQLCODE from UPDATE statement
             IF SQLCODE EQUAL 100
               MOVE '01' TO CA-RETURN-CODE
             ELSE
               MOVE '90' TO CA-RETURN-CODE
      *        Write error message to TD QUEUE(CSMT)
               PERFORM WRITE-ERROR-MESSAGE
             END-IF
           END-IF.
           EXIT.

      *================================================================*
      * Procedure to write error message to Queues                     *
      *   message will include Date, Time, Program Name, Customer      *
      *   Number, Policy Number and SQLCODE.                           *
      *================================================================*
       WRITE-ERROR-MESSAGE.
      * Save SQLCODE in message
           MOVE SQLCODE TO EM-SQLRC
      * Obtain and format current time and date
      *    EXEC CICS ASKTIME ABSTIME(WS-ABSTIME)
      *    END-EXEC
           DISPLAY '>>> MOCK ASKTIME @WRITE-ERROR-MESSAGE'
           MOVE 0 TO WS-ABSTIME
      *    EXEC CICS FORMATTIME ABSTIME(WS-ABSTIME)
      *              MMDDYYYY(WS-DATE)
      *              TIME(WS-TIME)
      *    END-EXEC
           DISPLAY '>>> MOCK FORMATTIME @WRITE-ERROR-MESSAGE'
           MOVE 0 TO WS-ABSTIME
           MOVE '01012024' TO WS-DATE
           MOVE '120000' TO WS-TIME
           MOVE WS-DATE TO EM-DATE
           MOVE WS-TIME TO EM-TIME
      * Write output message to TDQ
      *    EXEC CICS LINK PROGRAM('LGSTSQ')
      *              COMMAREA(ERROR-MSG)
      *              LENGTH(LENGTH OF ERROR-MSG)
      *    END-EXEC.
           DISPLAY '>>> MOCK LINK @WRITE-ERROR-MESSAGE: ' 'LGSTSQ'.
      * Write 90 bytes or as much as we have of commarea to TDQ
           IF EIBCALEN > 0 THEN
             IF EIBCALEN < 91 THEN
               MOVE DFHCOMMAREA(1:EIBCALEN) TO CA-DATA
      *        EXEC CICS LINK PROGRAM('LGSTSQ')
      *                  COMMAREA(CA-ERROR-MSG)
      *                  LENGTH(LENGTH OF CA-ERROR-MSG)
      *        END-EXEC
               DISPLAY '>>> MOCK LINK @WRITE-ERROR-MESSAGE: ' 'LGSTSQ'
             ELSE
               MOVE DFHCOMMAREA(1:90) TO CA-DATA
      *        EXEC CICS LINK PROGRAM('LGSTSQ')
      *                  COMMAREA(CA-ERROR-MSG)
      *                  LENGTH(LENGTH OF CA-ERROR-MSG)
      *        END-EXEC
               DISPLAY '>>> MOCK LINK @WRITE-ERROR-MESSAGE: ' 'LGSTSQ'
             END-IF
           END-IF.
           EXIT.
