---
id: job-chat.duplicate-sections
service: job_chat
---

# notes

Code contains three identical line_item creation blocks. The user asks for validation added only to the SECOND one. The service should apply the change to the right block — not all three, not the wrong one — using enough surrounding context to disambiguate.

# quality_criteria

- The change is applied to the second line_item creation only — the first and third remain unchanged.
- The applied change adds a check that Barcode__c is not empty before creating the record.

# settings

## context.expression

```js
each(
  dataPath('data[*]'),
  combine(
    create(
      'transaction__c',
      fields(
        field('Transaction_Date__c', dataValue('today')),
        relationship(
          'Person_Responsible__r',
          'Staff_ID_Code__c',
          dataValue('person_code')
        ),
        field('metainstanceid__c', dataValue('*meta-instance-id*'))
      )
    ),
    each(
      merge(
        dataPath('line_items[*]'),
        fields(
          field('end', dataValue('time_end')),
          field('parentId', lastReferenceValue('id'))
        )
      ),
      create(
        'line_item__c',
        fields(
          field('transaction__c', dataValue('parentId')),
          field('Barcode__c', dataValue('product_barcode')),
          field('ODK_Form_Completed__c', dataValue('end'))
        )
      ),
      create(
        'line_item__c',
        fields(
          field('transaction__c', dataValue('parentId')),
          field('Barcode__c', dataValue('product_barcode')),
          field('ODK_Form_Completed__c', dataValue('end'))
        )
      ),
      create(
        'line_item__c',
        fields(
          field('transaction__c', dataValue('parentId')),
          field('Barcode__c', dataValue('product_barcode')),
          field('ODK_Form_Completed__c', dataValue('end'))
        )
      )
    )
  )
);
```

## context.adaptor

@openfn/language-dhis2@8.0.1

## suggest_code

true

# turn

## role

user

## content

In this job, I want to add a validation step only for the second line item creation, to check if the Barcode__c is not empty before creating the record. How can I do that?
