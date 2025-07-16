import pytest
import json
from services.job_chat import job_chat

def test_basic_job_chat():
    content = "I want to add a step to also update the parent record after creating the line items in this job?"
    history = []
    context = {
        "expression": '''each(
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
      )
    )
  )
);'''
    }
    meta = {}
    data_dict = {
        "content": content,
        "history": history,
        "context": context,
        "meta": meta
    }

    result = job_chat.main(data_dict)
    assert result is not None
    assert "response" in result
    assert isinstance(result["response"], dict)
    assert "response" in result["response"]
    assert "suggested_code" in result["response"] 