---
id: global-chat.payment-reconciliation-pdf-to-whatsapp
service: global_chat
judges: [general, openfn_workflow_expert, openfn_code_quality]
---

# notes

Template-style request: a small business owner wants a recurring workflow that
reconciles payments against customer balances held in Google Sheets, generates a
per-customer PDF statement, sends it over WhatsApp, and writes the results back
to the sheet. The request is realistic and underspecified — it names no PDF tool,
no schedule, no field mappings, no WhatsApp template, and no error-handling
behaviour. A strong answer fills these gaps with sensible defaults (or surfaces
the key ambiguities) while producing a coherent multi-step workflow.

The YAML below is a **model answer**: a reference example of a good end-to-end
solution to this prompt. The model under test is **NOT** expected to reproduce it
exactly — adaptor versions, variable names, the PDF template markup, the exact
schedule, and the prose can all differ. It is provided so the judge has a concrete
sense of the shape, step breakdown, and capabilities a high-quality answer covers.
Judge against the quality_criteria, using the model answer only as a reference for
what "good" looks like — not as a string to diff against.

## Model answer (reference only — do not require exact replication)

```yaml
name: Payment Reconciliation PDF to WhatsApp
jobs:
  Retrieve-payment-and-customer-data-from-Gsheets:
    name: Retrieve payment and customer data from Gsheets
    adaptor: "@openfn/language-googlesheets@4.0.0"
    body: >-
      /**
       * Payment Reconciliation PDF to WhatsApp - OpenFn Template
       *
       * SETUP REQUIREMENTS:
       * 1. Google Sheets with customer data (columns: customer_name, customer_contact, total_balance_due, currency, sale_date, service_provided)
       * 2. WhatsApp Business Account with approved message template
       * 3. PDFShift account for PDF generation
       * 4. Credentials for Google Sheets and WhatsApp adaptors configured
       *
       * BEFORE RUNNING:
       * - Update the spreadsheetId
       * - Ensure WhatsApp template is approved with correct parameter count
       * - Set sandbox to false for production use for PDFshift adaptor
       * - Test with a small batch first
       */

      // First, we get customer information from a spreadsheet

      // It should contain their customer identification and total payment due

      getValues('1Q7HXKR-FQHVtvbgduvqqbag64jARs8MxYlHuHz2OjCA',
      'customer_information!A:G',

      );


      fn(state => {
       console.log('Customer information retrieved');

       const values = state.data.values;
       const headers = values[0];
       const dataRows = values.slice(1);

       // Map column indices
       const columnMap = {};
       headers.forEach((header, index) => {
         columnMap[header] = index;
       });

       // Convert to customer objects
       const customers = dataRows.map((row, rowIndex) => {
         return {
           rowIndex: rowIndex + 2,
           customerName: row[columnMap['customer_name']] || '',
           customerContact: row[columnMap['customer_contact']] || '',
           totalBalanceDue: parseFloat(row[columnMap['total_balance_due']] || 0),
           currency: row[columnMap['currency']] || 'USD',
           dueDate: row[columnMap['sale_date']] || '',
           serviceProvided: row[columnMap['service_provided']] || '',
           remainingBalance: parseFloat(row[columnMap['Remaining Balance']] || 0),
           // Initialize payment tracking
           totalPaid: 0,
           payments: []
         };
       }).filter(customer => customer.customerName);

       console.log(`Found ${customers.length} customers`);

       return {
         ...state,
         customers,
         customerColumnMap: columnMap,
         spreadsheetId: '1Q7HXKR-FQHVtvbgduvqqbag64jARs8MxYlHuHz2OjCA'
       };
      });


      // Then we get payment records from the payments received tab

      getValues('1Q7HXKR-FQHVtvbgduvqqbag64jARs8MxYlHuHz2OjCA',
      'payments_received!A:F',

      );


      fn(state => {
       console.log('Payment records retrieved');

       const paymentValues = state.data.values;
       const paymentHeaders = paymentValues[0];
       const paymentRows = paymentValues.slice(1);

       // Map payment column indices
       const paymentColumnMap = {};
       paymentHeaders.forEach((header, index) => {
         paymentColumnMap[header] = index;
       });

       // Process payment records
       const payments = paymentRows.map(row => {
         return {
           customer: row[paymentColumnMap['customer']] || '',
           dateReceived: row[paymentColumnMap['date_received']] || '',
           senderInfo: row[paymentColumnMap['sender_info']] || '',
           paymentType: row[paymentColumnMap['payment_type']] || '',
           amountPaid: parseFloat(row[paymentColumnMap['amount_paid']] || 0),
           currency: row[paymentColumnMap['currency']] || 'USD'
         };
       }).filter(payment => payment.amountPaid > 0); // Only keep payments with amount > 0;

       console.log(`Found ${payments.length} payment records`);

       // Merge payments with customers
       state.customers = state.customers.map(customer => {
         // Find all payments for this customer
         const customerPayments = payments.filter(payment =>
           payment.customer.toLowerCase().trim() === customer.customerName.toLowerCase().trim()
         );

         // Calculate total paid
         const totalPaid = customerPayments.reduce((sum, payment) => sum + payment.amountPaid, 0);

         // Calculate actual remaining balance
         const actualRemainingBalance = customer.totalBalanceDue - totalPaid;

         // Determine payment status for ALL customers
        let paymentStatus;
        if (totalPaid > customer.totalBalanceDue) {
          paymentStatus = 'OVERPAID';
        } else if (actualRemainingBalance <= 0) {
          paymentStatus = 'PAID IN FULL';
        } else if (totalPaid > 0) {
          paymentStatus = 'PARTIAL PAYMENT';
        } else {
          paymentStatus = 'UNPAID';
        }

         return {
           ...customer,
           payments: customerPayments,
           totalPaid,
           actualRemainingBalance,
           paymentStatus
         };
       });

       console.log('Customer and payment data merged successfully');

       return {
         ...state,
         processedCustomers: [],
         pdfResults: []
       };
      });
  Compute-customer-statement-content:
    name: Compute customer statement content
    adaptor: "@openfn/language-common@latest"
    body: >-

      // Step1: We generate the content to put in the PDF report to be sent to
      customers

      fn(state => {
        console.log('Computing balances and preparing data for PDF generation');

        const customersWithBalance = state.customers.map(customer => {
          // Determine status color based on payment status
          let statusColor;
          if (customer.paymentStatus === 'PAID IN FULL' || customer.paymentStatus === "OVERPAID") {
            statusColor = '#10b981';
          } else if (customer.paymentStatus === 'PARTIAL PAYMENT') {
            statusColor = '#f59e0b';
          } else if (customer.paymentStatus === 'UNPAID') {
            statusColor = '#dc2626';
          }

          // Calculate payment percentage
          const paymentPercentage = customer.totalBalanceDue > 0
            ? Math.min(100, Math.round((customer.totalPaid / customer.totalBalanceDue) * 100))
            : 0;

          // Generate HTML for this customer
          const html = generateStatementHTML({
            ...customer,
            statusColor,
            paymentPercentage
          });

          return {
            ...customer,
            statusColor,
            paymentPercentage,
            html,
            filename: `Statement_${customer.customerName.replace(/\s+/g, '_')}_${new Date().toISOString().split('T')[0]}.pdf`
          };
        });

        console.log('Balance computation complete');

        return { ...state, customersWithBalance };
      });


      // Step 2: Helper function to generate HTML (this is where you should
      change your template)

      function generateStatementHTML(customer) {
        const today = new Date().toLocaleDateString('en-GB');
        const timestamp = new Date().toISOString();

        return `
      <!DOCTYPE html>
      <html>
      <head>
        <meta charset="UTF-8">
        <style>
          @page { size: A4; margin: 12mm; }
          body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 0; color: #1e293b; line-height: 1.4; font-size: 13px; }
          .header { display: flex; align-items: center; justify-content: space-between; padding-bottom: 12px; margin-bottom: 16px; }
          .status-banner { background: linear-gradient(135deg, ${customer.statusColor} 0%, ${customer.statusColor}dd 100%); color: white; padding: 10px 16px; border-radius: 6px; text-align: center; margin-bottom: 16px; }
          .summary-cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 16px; }
          .summary-card { background: white; border: 1px solid #e2e8f0; padding: 12px; border-radius: 6px; text-align: center; }
          .payment-bar { background: #e2e8f0; height: 20px; border-radius: 10px; overflow: hidden; }
          .payment-bar-fill { background: linear-gradient(90deg, #10b981 0%, #059669 100%); height: 100%; width: ${customer.paymentPercentage}%; color: white; font-weight: 700; font-size: 11px; text-align: center; }
          table { width: 100%; border-collapse: collapse; margin-bottom: 16px; font-size: 11px; }
          table th { background: #cbc6dd; color: #1e293b; padding: 8px 10px; text-align: left; }
          table td { padding: 8px 10px; border-bottom: 1px solid #cbc6dd; background: white; }
        </style>
      </head>
      <body>
        <div class="header">
          <img class="logo" src="https://community.openfn.org/uploads/default/original/1X/d3705858aee0cd536578e52323d3beeac7336b0d.png" alt="OpenFn Logo" width="128" />
          <div class="document-title"><h1>ACCOUNT STATEMENT</h1><p>Generated: ${today}</p></div>
        </div>
        <div class="status-banner"><h2>Payment Status: ${customer.paymentStatus}</h2></div>
        <div class="summary-cards">
          <div class="summary-card"><h3>Total Due</h3><div class="amount">${customer.currency} ${customer.totalBalanceDue.toLocaleString()}</div></div>
          <div class="summary-card"><h3>Total Paid</h3><div class="amount">${customer.currency} ${customer.totalPaid.toLocaleString()}</div></div>
          <div class="summary-card highlight"><h3>Balance Remaining</h3><div class="amount">${customer.currency} ${customer.actualRemainingBalance.toLocaleString()}</div></div>
        </div>
        <div class="payment-bar-container">
          <div class="payment-bar-label">Payment Progress: ${customer.paymentPercentage}% Complete</div>
          <div class="payment-bar"><div class="payment-bar-fill">${customer.paymentPercentage}%</div></div>
        </div>
        ${customer.payments.length > 0 ? `
          <table>
            <thead><tr><th>Date</th><th>Payment Type</th><th>Sender</th><th style="text-align: right;">Amount</th></tr></thead>
            <tbody>
              ${customer.payments.map(payment => `
                <tr>
                  <td>${payment.dateReceived}</td>
                  <td>${payment.paymentType}</td>
                  <td>${payment.senderInfo}</td>
                  <td style="text-align: right; font-weight: 600;">${payment.currency} ${payment.amountPaid.toLocaleString()}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        ` : '<div class="no-payments">No payment records found</div>'}
        <div class="footer">
          <h3>Payment Instructions</h3>
          <p><strong>Reference:</strong> Please use "${customer.customerName}" as payment reference</p>
          <p><strong>Questions?</strong> Contact our support team at support@openfn.org</p>
        </div>
        <div class="footer-bottom">
          <p>Automated statement generated by <a href="https://www.openfn.org">OpenFn</a> • Document ID: ${customer.customerName.replace(/\s+/g, '')}-${timestamp.slice(0, 19).replace(/:/g, '').replace('T', '-')}</p>
        </div>
      </body>
      </html>
        `;
      }
  Generate-PDF:
    name: Generate PDF
    adaptor: "@openfn/language-pdfshift@latest"
    body: >

      // Step 1: We generate PDF statements for each of the customers

      each(
        '$.customersWithBalance[*]',
        fn(state => {
          console.log('== Starting iterating over customers ==');
          console.log('Current customer:', state.data.customerName);

          // Store customer for later reference
          state.currentCustomer = state.data;

          // Call generatePDF service
          return generatePDF(
            state.currentCustomer.html,
            {
              filename: state.currentCustomer.filename, // If we had a filename we will get a URL back, if none it will revert to base64 format
              encode: false, // To get base64 output
              sandbox: true  // Use sandbox for testing and false to remove their watermark and start counting API usage
            }
          )(state)
            .then(newState => {
              console.log('== After generatePDF step ==');

              if (!newState.pdfResults) newState.pdfResults = [];

              const pdfResponse = newState.data;

              //Getting the URL from the response
              const url = pdfResponse.url;

              // We push each PDF generated to an array
              newState.pdfResults.push({
                customerName: state.currentCustomer.customerName,
                filename: state.currentCustomer.filename,
                customerContact: state.currentCustomer.customerContact,
                currency: state.currentCustomer.currency,
                dueDate: state.currentCustomer.dueDate,
                actualRemainingBalance: state.currentCustomer.actualRemainingBalance,
                url: url,
                success: pdfResponse.success || false,
                generatedAt: new Date().toISOString()
              });

              return newState;
            })
            .catch (error=> {
                // Create results array if needed
              if (!state.pdfResults) state.pdfResults = [];

              // Log the error and add it to results
              console.log(`PDF generation error for ${state.currentCustomer.customerName}:`, error.message);

              state.pdfResults.push({
                customerName: state.currentCustomer.customerName,
                success: false,
                error: error.message,
                generatedAt: new Date().toISOString()
              });

              return state;
            });
        })
      );
  Send-via-Whatsapp:
    name: Send via Whatsapp
    adaptor: "@openfn/language-whatsapp@1.0.3"
    body: >-

      // Step 1: Initialize arrays to track progress

      fn(state => {
        console.log(`== Starting WhatsApp processing for ${state.pdfResults?.length || 0} customers ==`);

        // Initialize result tracking arrays
        state.whatsappResults = {
          successful: [],
          failed: [],
          skipped: []
        };

        return state;
      });


      // Step 2: Sending the PDF statement through the approved template to each
      customer

      each(
        'pdfResults[*]',
        fn(state => {
          const pdfResult = state.data;
          const customerName = pdfResult.customerName;
          const customerContact = pdfResult.customerContact;

          // Skip if no PDF link
          if (!pdfResult.success || !pdfResult.url|| !customerContact) {
            console.log(`Skipping ${pdfResult.customerName} - no PDF URL or no contact info`);

            state.whatsappResults.skipped.push({
              customerName,
              customerContact,
              reason: 'Missing PDF or contact info',
              timestamp: new Date().toISOString()
            });

            return state;
          }

          // Sending the request to the WhatsApp API
          return request(
            'POST',
            'messages',
            {
              messaging_product: 'whatsapp',
              to: customerContact, // Dynamic customer contact
              type: 'template',
              template: {
                name: 'account_statement_with_document', // Name of your template, should be approved first by Meta through the Business Management interface
                language: { code: 'en' },
                components: [
                  {
                    type: 'header',
                    parameters: [{
                      type: 'document',
                      document: {
                        link: pdfResult.url, // Dynamic PDF URL generated in previous step
                        filename: pdfResult.filename // Dynamic filename generated earlier
                      }
                    }]
                  },
                  {
                    type: 'body',
                    parameters: [
                      { type: 'text', text: customerName },
                      { type: 'text', text: new Date().toLocaleDateString('en-US', { month: 'long', year: 'numeric' }) },
                      { type: 'text', text: pdfResult.currency },
                      { type: 'text', text: pdfResult.actualRemainingBalance.toLocaleString() },
                      { type: 'text', text: new Date(new Date().setDate(new Date().getDate() + 30)).toLocaleDateString('en-US') }
                    ]
                  }
                ]
              }
            }
          )(state).then(successState => {
            //If success
            console.log(`Message sent to ${customerName}`);

            state.whatsappResults.successful.push({
              customerName,
              customerContact,
              messageId: successState.data?.messages?.[0]?.id,
              pdfUrl: pdfResult.url,
              timestamp: new Date().toISOString()
            });

            return { ...state, data: successState.data };

          }).catch((error, errorState) => {
            // ERROR - but continue processing
            console.error(`Failed to send to ${customerName}: ${error.message}`);

            state.whatsappResults.failed.push({
              customerName,
              customerContact,
              pdfUrl: pdfResult.url,
              error: error.message,
              timestamp: new Date().toISOString()
            });

            return state;
          });
        })
      );


      // Step 3:Prepare summary and spreadsheet updates

      fn(state => {
        const successful = state.whatsappResults.successful.length;
        const failed = state.whatsappResults.failed.length;
        const skipped = state.whatsappResults.skipped.length;
        const total = successful + failed + skipped;

        console.log('== WhatsApp processing complete ==');
        console.log(`Total: ${total} | Success: ${successful} | Failed: ${failed} | Skipped: ${skipped}`);

        // Prepare simple updates for spreadsheet
        state.allUpdates = [
          // Successful messages
          ...state.whatsappResults.successful.map(record => ({
            customerName: record.customerName,
            messageSent: 'YES',
            messageId: record.messageId,
            lastProcessed: record.timestamp,
            pdfLink: record.pdfUrl,
            status: 'SENT'
          })),

          // Failed messages
          ...state.whatsappResults.failed.map(record => ({
            customerName: record.customerName,
            messageSent: 'FAILED',
            messageId: null,
            lastProcessed: record.timestamp,
            pdfLink: record.pdfUrl,
            status: 'FAILED',
            errorMessage: record.error
          })),

          // Skipped customers
          ...state.whatsappResults.skipped.map(record => ({
            customerName: record.customerName,
            messageSent: 'SKIPPED',
            messageId: null,
            lastProcessed: record.timestamp,
            pdfLink: null,
            status: 'SKIPPED',
            errorMessage: record.reason
          }))
        ];

        console.log(`Prepared ${state.allUpdates.length} spreadsheet updates`);
        return state;
      });
  Update-spreadsheet:
    name: Update spreadsheet
    adaptor: "@openfn/language-googlesheets@4.0.1"
    body: >-

      // Step 1: Prepare batch update

      fn(state => {
        console.log('== Updating Google Sheets with WhatsApp Results ==');
        state.spreadsheetId = '1Q7HXKR-FQHVtvbgduvqqbag64jARs8MxYlHuHz2OjCA';

        // Initialize tracking arrays
        state.spreadsheetUpdatesComplete = [];
        state.spreadsheetUpdatesFailed = [];

        if (!state.allUpdates || state.allUpdates.length === 0) {
          console.log('No updates to process - skipping spreadsheet update');
          return state;
        }

        console.log(`Processing ${state.allUpdates.length} customer updates`);

        state.batchUpdates = state.allUpdates.map(update => ({
          customerName: update.customerName,
          messageSent: update.messageSent || 'No',
          messageId: update.messageId || '',
          lastProcessed: update.lastProcessed,
          pdfLink: update.pdfLink || '',
          status: update.status || 'Failed',
          errorMessage: update.errorMessage || ''
        }));

        return state;
      });


      // Step 2: Load ALL columns and check for missing ones

      fn(state => {
        console.log('Loading full spreadsheet data and checking columns...');

        const requiredColumns = [
          'Message Sent',
          'WhatsApp Message ID',
          'PDF Link',
          'Last Processed',
          'Error Message',
          'Remaining Balance'
        ];

        return getValues(
          state.spreadsheetId,
          'customer_information!1:1'
        )(state).then(headerState => {

          const currentHeaders = headerState.data.values?.[0] || [];
          console.log('Current headers:', currentHeaders);

          // Store the original customer data from earlier steps
          headerState.originalCustomers = state.customers;

          // Build column map
          const columnMap = {};
          currentHeaders.forEach((header, index) => {
            columnMap[header] = index;
          });

          // Check for missing columns
          const missingColumns = requiredColumns.filter(col => !currentHeaders.includes(col));

          if (missingColumns.length > 0) {
            console.log(`Need to add missing columns: ${missingColumns.join(', ')}`);
            headerState.needsColumnUpdate = true;
            headerState.missingColumns = missingColumns;
            headerState.currentHeaders = currentHeaders;
          } else {
            console.log('All required tracking columns exist');
            headerState.needsColumnUpdate = false;
          }

          headerState.customerColumnMap = columnMap;
          return headerState;
        });
      });


      // Step 3: Add missing columns if needed

      fn(state => {
        if (!state.needsColumnUpdate) {
          console.log('No columns to add');
          return state;
        }

        console.log(`Adding ${state.missingColumns.length} missing columns...`);

        const newHeaders = [...state.currentHeaders, ...state.missingColumns];

        return batchUpdateValues({
          spreadsheetId: state.spreadsheetId,
          range: 'customer_information!1:1',
          valueInputOption: 'USER_ENTERED',
          values: [newHeaders]
        })(state).then(updateState => {
          console.log('Headers updated successfully');

          // Rebuild column map with new headers
          const columnMap = {};
          newHeaders.forEach((header, index) => {
            columnMap[header] = index;
          });

          updateState.customerColumnMap = columnMap;
          updateState.currentHeaders = newHeaders;
          return updateState;
        });
      });


      // Step 4: Load the full data with all customers

      fn(state => {
        console.log('Loading customer data with row indices...');

        // Determine the range based on whether we added columns
        const lastColumn = String.fromCharCode(65 + (state.currentHeaders?.length || 26) - 1);
        const range = `customer_information!A:${lastColumn}`;

        return getValues(
          state.spreadsheetId,
          range
        )(state).then(dataState => {
          const rows = dataState.data.values || [];
          const headers = rows[0];

          // Find customer name column index
          const customerNameCol = headers.indexOf('customer_name');

          if (customerNameCol === -1) {
            throw new Error('Could not find customer_name column');
          }

          // Build customer list with row indices
          dataState.spreadsheetCustomers = [];
          for (let i = 1; i < rows.length; i++) {
            if (rows[i] && rows[i][customerNameCol]) {
              dataState.spreadsheetCustomers.push({
                customerName: rows[i][customerNameCol],
                rowIndex: i + 1,
                rowData: rows[i]
              });
            }
          }

          console.log(`Found ${dataState.spreadsheetCustomers.length} customers in spreadsheet`);
          return dataState;
        });
      });


      // Step 5: Update customer rows

      each(
        'batchUpdates[*]',
        fn(state => {
          const updateData = state.data;
          const customerName = updateData.customerName;

          // Find the customer in spreadsheet data
          const spreadsheetCustomer = state.spreadsheetCustomers?.find(c =>
            c.customerName?.toLowerCase().trim() === customerName.toLowerCase().trim()
          );

          if (!spreadsheetCustomer) {
            console.log(`Customer not found in spreadsheet`);
            state.spreadsheetUpdatesFailed.push({
              customerName: customerName,
              error: 'Customer not found'
            });
            return state;
          }

          // Find original customer for remaining balance
          const originalCustomer = state.originalCustomers?.find(c =>
            c.customerName?.toLowerCase().trim() === customerName.toLowerCase().trim()
          );

          const rowIndex = spreadsheetCustomer.rowIndex;
          const columnMap = state.customerColumnMap;

          // Build updated row
          const rowValues = [...(spreadsheetCustomer.rowData || [])];
          const maxColumns = state.currentHeaders?.length || Math.max(...Object.values(columnMap)) + 1;

          while (rowValues.length < maxColumns) {
            rowValues.push('');
          }

          // Update tracking columns
          if (columnMap['Message Sent'] !== undefined) {
            rowValues[columnMap['Message Sent']] = updateData.messageSent;
          }
          if (columnMap['WhatsApp Message ID'] !== undefined) {
            rowValues[columnMap['WhatsApp Message ID']] = updateData.messageId || '';
          }
          if (columnMap['PDF Link'] !== undefined) {
            rowValues[columnMap['PDF Link']] = updateData.pdfLink || '';
          }
          if (columnMap['Last Processed'] !== undefined) {
            rowValues[columnMap['Last Processed']] = updateData.lastProcessed || '';
          }
          if (columnMap['Error Message'] !== undefined) {
            rowValues[columnMap['Error Message']] = updateData.errorMessage || '';
          }
          if (columnMap['Remaining Balance'] !== undefined && originalCustomer) {
            rowValues[columnMap['Remaining Balance']] = originalCustomer.actualRemainingBalance?.toString() || '';
          }

          console.log(`Updating row ${rowIndex} with ${rowValues.length} columns`);

          // Update the row
          return batchUpdateValues({
            spreadsheetId: state.spreadsheetId,
            range: `customer_information!${rowIndex}:${rowIndex}`,
            valueInputOption: 'USER_ENTERED',
            values: [rowValues]
          })(state).then(result => {
            console.log(`Updated customer at row ${rowIndex}`);
            state.spreadsheetUpdatesComplete.push({
              customerName: customerName,
              rowIndex: rowIndex
            });
            return state;
          }).catch(error => {
            console.error(`Failed to update customer `, error.message);
            state.spreadsheetUpdatesFailed.push({
              customerName: customerName,
              rowIndex: rowIndex,
              error: error.message
            });
            return state;
          });
        })
      );


      // Step 6: Final summary

      fn(state => {
        const successCount = state.spreadsheetUpdatesComplete?.length || 0;
        const failureCount = state.spreadsheetUpdatesFailed?.length || 0;
        const totalAttempted = state.batchUpdates?.length || 0;

        console.log('\n=== SPREADSHEET UPDATE SUMMARY ===');
        console.log(`Total Attempted: ${totalAttempted}`);
        console.log(`Successfully Updated: ${successCount}`);
        console.log(`Failed Updates: ${failureCount}`);

        if (failureCount > 0) {
          console.log('\n--- FAILED SPREADSHEET UPDATES ---');
          state.spreadsheetUpdatesFailed?.forEach((failure, index) => {
            console.log(`${index + 1}. ${failure.customerName}: ${failure.error}`);
          });
        }

        return state;
      });
triggers:
  cron:
    type: cron
    enabled: true
    cron_expression: 00 13 * * 01
    cron_cursor_job: null
edges:
  cron->Retrieve-payment-and-customer-data-from-Gsheets:
    condition_type: always
    enabled: true
    target_job: Retrieve-payment-and-customer-data-from-Gsheets
    source_trigger: cron
  Retrieve-payment-and-customer-data-from-Gsheets->Compute-customer-statement-content:
    condition_type: on_job_success
    enabled: true
    target_job: Compute-customer-statement-content
    source_job: Retrieve-payment-and-customer-data-from-Gsheets
  Compute-customer-statement-content->Generate-PDF:
    condition_type: on_job_success
    enabled: true
    target_job: Generate-PDF
    source_job: Compute-customer-statement-content
  Generate-PDF->Send-via-Whatsapp:
    condition_type: on_job_success
    enabled: true
    target_job: Send-via-Whatsapp
    source_job: Generate-PDF
  Send-via-Whatsapp->Update-spreadsheet:
    condition_type: on_job_success
    enabled: true
    target_job: Update-spreadsheet
    source_job: Send-via-Whatsapp
```

# quality_criteria

- The response produces a coherent multi-step workflow that covers the full pipeline: read customer + payment data from Google Sheets, reconcile payments against balances, generate a per-customer PDF statement, send it over WhatsApp, and write results back to the sheet.
- Reconciliation logic correctly matches payments to customers (e.g. by name, case-insensitively), sums amounts paid, computes the remaining balance, and derives a payment status (paid / partial / unpaid, and ideally overpaid).
- Each step uses functions appropriate to its adaptor (googlesheets for read/write, a PDF generation step, whatsapp for sending), and iterates per-customer where the operation is per-customer (e.g. each() over the customer/PDF list).
- The workflow handles the realistic ambiguities the user left open — it either makes sensible, clearly-stated default choices (PDF tool, schedule, WhatsApp template, write-back columns) or surfaces them as assumptions/clarifying points, rather than silently ignoring them.
- The write-back step records per-customer outcome (sent / failed / skipped) back to the spreadsheet, and the send/PDF steps degrade gracefully on per-customer failure rather than aborting the whole run.
- The model answer YAML in the notes is a **reference only**: the response is judged on whether it is functionally equivalent and covers the same capabilities, NOT on exact replication of that YAML (adaptor versions, variable names, PDF markup, and schedule may all legitimately differ).

# turn

## role

user

## content

Every Monday I need to send each of my customers a payment statement. I keep all the customer info and the payments I've received in a Google Sheet. Can you build something that figures out who has paid, who still owes money, and how much, then makes a nice PDF statement for each person and sends it to them on WhatsApp? Also it would be good to write back to the sheet so I can see who got their message.
